"""Streaming GRIB-to-Zarr conversion and resumable checkpoints."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import zarr

from forecast_zarr.config import ProcessorConfig
from forecast_zarr.errors import BudgetExceededError, InputContractError
from forecast_zarr.grib import EccodesReader, GribReader
from forecast_zarr.inspection import match_message, selected_message_keys
from forecast_zarr.io import directory_size, read_json, write_json_atomic
from forecast_zarr.models import ArrayLayout, InspectionReport, ProcessingPlan
from forecast_zarr.normalization import (
    normalize_values,
    regular_grid,
)
from forecast_zarr.store import ForecastStore

GIB = 1024**3


def ingestion_path(plan: ProcessingPlan) -> Path:
    """Private resumable store whose chunks are safe for one-time-slice writes."""
    return plan.staging_path.with_name(f"{plan.dataset_id}.ingest.zarr")


def _ingestion_plan(plan: ProcessingPlan) -> ProcessingPlan:
    latitude = len(plan.grid.latitude)
    longitude = len(plan.grid.longitude)
    variables = []
    for variable in plan.variables:
        itemsize = np.dtype(variable.encoding.dtype).itemsize
        chunks = (1, min(360, latitude), min(360, longitude))
        layout = ArrayLayout(
            chunks=chunks,
            shards=chunks,
            uncompressed_shard_bytes=int(np.prod(chunks)) * itemsize,
        )
        variables.append(variable.model_copy(update={"layout": layout}))
    return plan.model_copy(
        update={"staging_path": ingestion_path(plan), "variables": tuple(variables)}
    )


def _checkpoint_path(path: Path) -> Path:
    return path / "provenance" / "checkpoint.json"


def _load_checkpoint(path: Path, dataset_id: str) -> set[str]:
    checkpoint = _checkpoint_path(path)
    if not checkpoint.exists():
        return set()
    raw = read_json(checkpoint)
    if not isinstance(raw, dict) or raw.get("dataset_id") != dataset_id:
        raise InputContractError("invalid or foreign staging checkpoint")
    processed = raw.get("processed", [])
    if not isinstance(processed, list):
        raise InputContractError("invalid staging checkpoint entries")
    return {str(item) for item in processed}


def _save_checkpoint(path: Path, dataset_id: str, processed: set[str]) -> None:
    write_json_atomic(
        _checkpoint_path(path),
        {"schema_version": "1.0", "dataset_id": dataset_id, "processed": sorted(processed)},
    )


def _guard_disk(config: ProcessorConfig, plan: ProcessingPlan) -> None:
    size = directory_size(plan.staging_path)
    if size > config.storage.max_zarr_output_gib * GIB:
        raise BudgetExceededError("staging store exceeded max_zarr_output_gib")
    free = shutil.disk_usage(plan.staging_path).free
    if free < config.storage.min_free_gib * GIB:
        raise BudgetExceededError("free space fell below min_free_gib during conversion")


def convert_messages(
    config: ProcessorConfig,
    plan: ProcessingPlan,
    report: InspectionReport,
    *,
    reader: GribReader | None = None,
) -> ForecastStore:
    """Write source GRIB fields sequentially without calculating new variables."""
    decoder = reader or EccodesReader()
    plan = _ingestion_plan(plan)
    if plan.staging_path.exists():
        if not config.resume:
            raise InputContractError(
                f"staging directory already exists and resume is disabled: {plan.staging_path}"
            )
        store = ForecastStore.open(plan.staging_path, plan)
        processed = _load_checkpoint(plan.staging_path, plan.dataset_id)
    else:
        store = ForecastStore.create(plan.staging_path, plan, report, config)
        processed = set()
        _save_checkpoint(plan.staging_path, plan.dataset_id, processed)
    plans = {item.name: item for item in plan.variables}
    selected = selected_message_keys(report.messages)
    message_counter = 0
    for source_file in report.source_files:
        for decoded in decoder.iter_file(report.input_dir / source_file.name):
            key = f"message:{source_file.name}:{decoded.meta.message_index}"
            if key in processed:
                continue
            if decoded.meta.source_key not in selected:
                processed.add(key)
                _save_checkpoint(plan.staging_path, plan.dataset_id, processed)
                continue
            spec = match_message(decoded.meta)
            if spec is None:
                processed.add(key)
                _save_checkpoint(plan.staging_path, plan.dataset_id, processed)
                continue
            variable = plans.get(spec.name)
            if variable is not None:
                canonical = normalize_values(spec, decoded.values, decoded.meta.units)
                lat, lon, values = regular_grid(
                    decoded.latitudes,
                    decoded.longitudes,
                    canonical,
                    convention=config.longitude_convention,
                )
                store.write_block(variable, decoded.meta.valid_time, lat, lon, values)
            processed.add(key)
            _save_checkpoint(plan.staging_path, plan.dataset_id, processed)
            message_counter += 1
            if message_counter % 8 == 0:
                _guard_disk(config, plan)
    _save_checkpoint(plan.staging_path, plan.dataset_id, processed)
    _guard_disk(config, plan)
    return store


def _owned_store(path: Path, dataset_id: str) -> bool:
    try:
        root = zarr.open_group(store=path, mode="r", zarr_format=3)
    except Exception:
        return False
    return root.attrs.get("dataset_id") == dataset_id


def assemble_final_store(
    config: ProcessorConfig,
    plan: ProcessingPlan,
    report: InspectionReport,
) -> Path:
    """Rechunk the ingestion store into the immutable consumer layout tile by tile."""
    source_path = ingestion_path(plan)
    if not source_path.exists() or not _owned_store(source_path, plan.dataset_id):
        raise InputContractError("complete owned ingestion staging store is missing")
    if plan.staging_path.exists():
        if not _owned_store(plan.staging_path, plan.dataset_id):
            raise InputContractError("final staging path is foreign or invalid")
        return plan.staging_path

    assembly_path = plan.staging_path.with_name(f"{plan.dataset_id}.rechunking.zarr")
    if assembly_path.exists():
        if not _owned_store(assembly_path, plan.dataset_id):
            raise InputContractError("rechunk staging path is foreign or invalid")
        shutil.rmtree(assembly_path)

    source = ForecastStore.open(source_path, _ingestion_plan(plan), mode="r")
    target = ForecastStore.create(assembly_path, plan, report, config)
    try:
        for variable in plan.variables:
            source_array = source.array(variable)
            target_array = target.array(variable)
            _, y_chunk, x_chunk = variable.layout.chunks
            for y0 in range(0, target_array.shape[1], y_chunk):
                y1 = min(target_array.shape[1], y0 + y_chunk)
                for x0 in range(0, target_array.shape[2], x_chunk):
                    x1 = min(target_array.shape[2], x0 + x_chunk)
                    target_array[:, y0:y1, x0:x1] = source_array[:, y0:y1, x0:x1]
                    _guard_disk(config, plan.model_copy(update={"staging_path": assembly_path}))
    except Exception:
        # Keep the owned directory for diagnosis; the next resumable run rebuilds it.
        raise
    assembly_path.replace(plan.staging_path)
    return plan.staging_path


def remove_ingestion_staging(plan: ProcessingPlan) -> None:
    """Remove only this processor's verified private staging store after publication."""
    path = ingestion_path(plan)
    if path.exists():
        if not _owned_store(path, plan.dataset_id):
            raise InputContractError("refusing to remove foreign ingestion staging store")
        shutil.rmtree(path)
