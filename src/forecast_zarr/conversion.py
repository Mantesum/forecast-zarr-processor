"""Streaming GRIB-to-Zarr conversion and resumable checkpoints."""

from __future__ import annotations

import shutil
from pathlib import Path

from forecast_zarr.config import ProcessorConfig
from forecast_zarr.errors import BudgetExceededError, InputContractError
from forecast_zarr.grib import EccodesReader, GribReader
from forecast_zarr.inspection import match_message, selected_message_keys
from forecast_zarr.io import directory_size, read_json, write_json_atomic
from forecast_zarr.models import InspectionReport, ProcessingPlan
from forecast_zarr.normalization import (
    normalize_values,
    regular_grid,
)
from forecast_zarr.store import ForecastStore

GIB = 1024**3


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
