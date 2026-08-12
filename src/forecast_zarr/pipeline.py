"""discover -> inspect -> plan -> convert -> validate -> publish orchestration."""

from __future__ import annotations

import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy
import zarr

from forecast_zarr import __version__
from forecast_zarr.config import ProcessorConfig
from forecast_zarr.conversion import (
    assemble_final_store,
    convert_messages,
    remove_ingestion_staging,
)
from forecast_zarr.errors import InputContractError
from forecast_zarr.grib import EccodesReader, GribReader
from forecast_zarr.hashing import sha256_file, sha256_json
from forecast_zarr.inspection import inspect_run, source_input_hash
from forecast_zarr.io import directory_size, read_json, write_json_atomic
from forecast_zarr.models import InspectionReport, ProcessingPlan, SourceManifest
from forecast_zarr.planning import create_plan, enforce_budget
from forecast_zarr.validation import validate_round_trip, validate_structure


def plan_cache_path(config_path: Path) -> Path:
    """Return the private cache shared by the plan and convert CLI invocations."""
    return config_path.with_name(f"{config_path.name}.plan-cache.json")


def _config_hash(config: ProcessorConfig) -> str:
    return sha256_json(config.model_dump(mode="json"))


def save_plan_cache(
    config_path: Path,
    config: ProcessorConfig,
    report: InspectionReport,
    plan: ProcessingPlan,
) -> None:
    write_json_atomic(
        plan_cache_path(config_path),
        {
            "schema_version": "1.0",
            "processor_version": __version__,
            "config_hash": _config_hash(config),
            "report": report.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
        },
    )


def load_plan_cache(
    config_path: Path, config: ProcessorConfig
) -> tuple[InspectionReport, ProcessingPlan] | None:
    """Reuse a plan only while its config, manifest, and source file sizes are unchanged."""
    path = plan_cache_path(config_path)
    if not path.is_file():
        return None
    raw = read_json(path)
    if (
        not isinstance(raw, dict)
        or raw.get("processor_version") != __version__
        or raw.get("config_hash") != _config_hash(config)
    ):
        return None
    try:
        report = InspectionReport.model_validate(raw.get("report"))
        plan = ProcessingPlan.model_validate(raw.get("plan"))
    except ValueError:
        return None
    if not report.manifest_path.is_file():
        return None
    try:
        manifest = SourceManifest.model_validate(read_json(report.manifest_path))
    except (OSError, ValueError):
        return None
    if source_input_hash(manifest) != report.input_hash:
        return None
    if any(
        not (report.input_dir / item.name).is_file()
        or (report.input_dir / item.name).stat().st_size != item.size
        for item in report.source_files
    ):
        return None
    current_manifest_hash = sha256_file(report.manifest_path)
    report = report.model_copy(
        update={
            "manifest_hash": current_manifest_hash,
            "license": manifest.license,
            "attribution": manifest.attribution,
        }
    )
    return report, plan


def build_plan(
    config: ProcessorConfig, *, reader: GribReader | None = None
) -> tuple[InspectionReport, ProcessingPlan]:
    report = inspect_run(config, reader=reader)
    plan = create_plan(config, report)
    return report, plan


def prepare_plan(
    config_path: Path,
    config: ProcessorConfig,
    *,
    reader: GribReader | None = None,
) -> tuple[InspectionReport, ProcessingPlan]:
    """Reuse a valid cached plan or build and persist one for a new source identity."""
    prepared = load_plan_cache(config_path, config)
    if prepared is None:
        prepared = build_plan(config, reader=reader)
    save_plan_cache(config_path, config, *prepared)
    return prepared


def _critical_metadata_checksum(path: Path) -> str:
    documents: list[tuple[str, str]] = []
    for item in sorted(path.rglob("zarr.json")):
        documents.append((item.relative_to(path).as_posix(), sha256_file(item)))
    return sha256_json(documents)


def _software_versions(reader: GribReader) -> dict[str, str]:
    return {
        "forecast_zarr_processor": __version__,
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "zarr": zarr.__version__,
        "eccodes": reader.version(),
    }


def run_convert(
    config: ProcessorConfig,
    *,
    reader: GribReader | None = None,
    prepared: tuple[InspectionReport, ProcessingPlan] | None = None,
) -> Path:
    """Execute all stages and atomically expose only a READY store."""
    decoder = reader or EccodesReader()
    started = datetime.now(UTC)
    clock = time.perf_counter()
    report, plan = prepared or build_plan(config, reader=decoder)
    enforce_budget(plan)
    if plan.output_path.exists():
        ready_path = plan.output_path / "READY.json"
        if ready_path.is_file():
            ready = read_json(ready_path)
            if isinstance(ready, dict) and ready.get("dataset_id") == plan.dataset_id:
                return plan.output_path
        raise InputContractError(
            f"final path exists without matching READY.json: {plan.output_path}"
        )
    write_started = time.perf_counter()
    convert_messages(config, plan, report, reader=decoder)
    assemble_final_store(config, plan, report)
    conversion_seconds = time.perf_counter() - write_started
    structural = validate_structure(
        plan.staging_path,
        plan,
        require_ready=False,
        time_samples=config.validation.time_samples,
    )
    round_trip = validate_round_trip(plan.staging_path, config, plan, report, reader=decoder)
    metadata_checksum = _critical_metadata_checksum(plan.staging_path)
    versions = _software_versions(decoder)
    completed = datetime.now(UTC)
    source_manifest = read_json(report.manifest_path)
    write_json_atomic(
        plan.staging_path / "provenance" / "source-manifest.json",
        source_manifest,
    )
    actual_size = 0
    processing_manifest: dict[str, Any] = {
        "schema_version": "1.1",
        "dataset_id": plan.dataset_id,
        "input_manifest": "provenance/source-manifest.json",
        "input_manifest_sha256": report.manifest_hash,
        "input_hash": report.input_hash,
        "source_files": [
            {"name": item.name, "size": item.size, "checksum": item.checksum}
            for item in report.source_files
        ],
        "provider": plan.provider,
        "model": plan.model,
        "run_utc": plan.run_utc.isoformat(),
        "variables": [item.name for item in plan.variables],
        "valid_times": [item.isoformat() for item in plan.valid_times],
        "software_versions": versions,
        "layout": {
            item.name: {
                "chunks": item.layout.chunks,
                "shards": item.layout.shards,
            }
            for item in plan.variables
        },
        "encoding": {item.name: item.encoding.model_dump(mode="json") for item in plan.variables},
        "actual_size_bytes": actual_size,
        "critical_metadata_sha256": metadata_checksum,
        "processing": {
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
            "total_seconds": time.perf_counter() - clock,
            "conversion_seconds": conversion_seconds,
        },
        "validation": {"structural": structural, "round_trip": round_trip},
        "status": "ready",
        "license": report.license,
        "attribution": report.attribution,
        "plan": plan.model_dump(mode="json"),
    }
    ready_keys = (
        "schema_version",
        "dataset_id",
        "input_manifest_sha256",
        "input_hash",
        "source_files",
        "provider",
        "model",
        "run_utc",
        "variables",
        "valid_times",
        "software_versions",
        "layout",
        "encoding",
        "actual_size_bytes",
        "critical_metadata_sha256",
        "processing",
        "status",
        "license",
        "attribution",
    )
    for _ in range(3):
        processing_manifest["actual_size_bytes"] = actual_size
        ready = {key: processing_manifest[key] for key in ready_keys}
        write_json_atomic(
            plan.staging_path / "provenance" / "processing-manifest.json",
            processing_manifest,
        )
        write_json_atomic(plan.staging_path / "READY.json", ready)
        measured_size = directory_size(plan.staging_path)
        if measured_size == actual_size:
            break
        actual_size = measured_size
    plan.output_path.parent.mkdir(parents=True, exist_ok=True)
    plan.staging_path.replace(plan.output_path)
    remove_ingestion_staging(plan)
    return plan.output_path
