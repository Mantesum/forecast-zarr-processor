"""Deterministic conversion plan and conservative budget enforcement."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from forecast_zarr.config import EncodingMode, ProcessorConfig
from forecast_zarr.errors import BudgetExceededError, InputContractError
from forecast_zarr.hashing import sha256_json
from forecast_zarr.layout import choose_layout
from forecast_zarr.models import (
    ArrayEncoding,
    BudgetReport,
    InspectionReport,
    ProcessingPlan,
    VariableInventory,
    VariablePlan,
)
from forecast_zarr.normalization import SPECS_BY_NAME, compact_encoding

GIB = 1024**3


def _existing_ancestor(path: Path) -> Path:
    candidate = path.resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _tree_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _encoding(mode: EncodingMode, inventory: VariableInventory, name: str) -> ArrayEncoding:
    if mode is EncodingMode.LOSSLESS:
        return ArrayEncoding(
            dtype="float32",
            fill_value=float("nan"),
            maximum_absolute_error=0,
        )
    spec = SPECS_BY_NAME[name]
    return compact_encoding(spec, inventory.minimum, inventory.maximum)


def create_plan(config: ProcessorConfig, report: InspectionReport) -> ProcessingPlan:
    """Choose arrays/layouts and reject unsafe disk or memory projections."""
    by_name = {item.name: item for item in report.variables}
    required_missing = set(config.required_variables) - set(by_name)
    required_missing.update(
        name
        for name in set(config.required_variables) & set(by_name)
        if by_name[name].minimum is None and by_name[name].maximum is None
    )
    if required_missing:
        raise InputContractError(f"required variables are missing: {sorted(required_missing)}")

    variables: list[VariablePlan] = []
    warnings: list[str] = []
    configured_names = [name for name in config.variables if name in by_name]
    selected_names = [
        *configured_names,
        *(name for name in by_name if name not in configured_names),
    ]
    for name in config.variables:
        if name not in SPECS_BY_NAME:
            warnings.append(f"configured calculated or unknown variable ignored: {name}")
        elif name not in by_name:
            warnings.append(f"configured source variable missing: {name}")
    shape_spatial = (len(report.grid.latitude), len(report.grid.longitude))
    global_valid_times = tuple(sorted({meta.valid_time for meta in report.messages}))
    for name in selected_names:
        spec = SPECS_BY_NAME[name]
        item = by_name[name]
        if item.duplicate_count:
            warnings.append(
                f"{name} has {item.duplicate_count} repeated time/field messages; "
                "coordinate overlaps will be checked during conversion"
            )
        encoding = _encoding(config.encoding, item, name)
        itemsize = 2 if encoding.dtype == "int16" else 4
        layout = choose_layout((len(global_valid_times), *shape_spatial), itemsize, config.chunking)
        variables.append(
            VariablePlan(
                name=name,
                required=name in config.required_variables,
                group=spec.group,
                units=spec.units,
                standard_name=spec.standard_name,
                long_name=spec.long_name,
                source_short_names=item.source_short_names,
                source_levels=item.source_levels,
                valid_times=item.valid_times,
                encoding=encoding,
                layout=layout,
            )
        )
        if encoding.fallback_reason:
            warnings.append(f"{name} uses float32: {encoding.fallback_reason}")

    if not variables:
        raise InputContractError("none of the selected variables are available")
    valid_times = global_valid_times
    cells = shape_spatial[0] * shape_spatial[1]
    raw_bytes = sum(
        cells * len(item.valid_times) * (2 if item.encoding.dtype == "int16" else 4)
        for item in variables
    )
    estimated_output = int(raw_bytes * 0.9) + 8 * 1024 * 1024
    estimated_temp = min(256 * 1024 * 1024, max(32 * 1024 * 1024, estimated_output // 50))
    max_message_cells = max(meta.ni * meta.nj for meta in report.messages)
    max_shard = max(item.layout.uncompressed_shard_bytes for item in variables)
    peak_memory = max_message_cells * 34 + max_shard * 2 + 64 * 1024 * 1024
    free = shutil.disk_usage(_existing_ancestor(config.output_root)).free
    existing = _tree_size(config.output_root)
    projected_free = free - estimated_output - estimated_temp
    reasons: list[str] = []
    if estimated_output > config.storage.max_zarr_output_gib * GIB:
        reasons.append("estimated output exceeds max_zarr_output_gib")
    if estimated_temp > config.storage.max_temporary_gib * GIB:
        reasons.append("estimated temporary use exceeds max_temporary_gib")
    if existing + estimated_output > config.storage.total_budget_gib * GIB:
        reasons.append("managed output plus estimate exceeds total_budget_gib")
    if projected_free < config.storage.min_free_gib * GIB:
        reasons.append("projected free space is below min_free_gib")
    if peak_memory > config.runtime.memory_budget_gib * GIB:
        reasons.append("estimated peak memory exceeds memory_budget_gib")

    identity: dict[str, Any] = {
        "input_hash": report.input_hash,
        "encoding": config.encoding.value,
        "longitude_convention": config.longitude_convention,
        "variables": [item.name for item in variables],
        "crop_to_manifest_regions": config.crop_to_manifest_regions,
        "chunking": config.chunking.model_dump(mode="json"),
        "compression_level": config.compression_level,
        "processor_schema": "2.0",
    }
    dataset_id = sha256_json(identity)[:24]
    run = report.run_utc.strftime("%Y%m%dT%H%M%SZ")
    output_path = (
        config.output_root / report.provider / report.model / run / f"{dataset_id}.zarr"
    ).resolve()
    staging_path = (config.output_root / ".staging" / f"{dataset_id}.zarr").resolve()
    budget = BudgetReport(
        estimated_output_bytes=estimated_output,
        estimated_temporary_bytes=estimated_temp,
        estimated_peak_memory_bytes=peak_memory,
        current_free_bytes=free,
        projected_free_bytes=projected_free,
        passes=not reasons,
        reasons=tuple(reasons),
    )
    return ProcessingPlan(
        dataset_id=dataset_id,
        input_hash=report.input_hash,
        provider=report.provider,
        model=report.model,
        run_utc=report.run_utc,
        output_path=output_path,
        staging_path=staging_path,
        variables=tuple(variables),
        valid_times=valid_times,
        grid=report.grid,
        encoding_mode=config.encoding.value,
        budget=budget,
        warnings=tuple(
            [*warnings, *(f"unmapped GRIB message: {item}" for item in report.unknown_messages)]
        ),
    )


def enforce_budget(plan: ProcessingPlan) -> None:
    """Refuse conversion before Zarr creation when any hard limit fails."""
    if not plan.budget.passes:
        raise BudgetExceededError("; ".join(plan.budget.reasons))
