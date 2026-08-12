from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import zarr

from forecast_zarr.config import ChunkingConfig
from forecast_zarr.conversion import (
    _copy_variable,
    assemble_final_store,
    convert_messages,
)
from forecast_zarr.errors import InputContractError, ValidationError
from forecast_zarr.pipeline import (
    build_plan,
    load_plan_cache,
    run_convert,
    save_plan_cache,
)
from forecast_zarr.store import ForecastStore
from forecast_zarr.validation import validate_structure
from tests.helpers import (
    decoded_message,
    energy_source_run,
    processor_config,
    real_grib_source_run,
    source_run,
)


def test_end_to_end_writes_ready_zarr_v3_and_is_idempotent(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    config = processor_config(tmp_path, run_dir)
    output = run_convert(config, reader=reader)
    assert output.is_dir()
    ready = json.loads((output / "READY.json").read_text(encoding="utf-8"))
    assert ready["status"] == "ready"
    assert not (config.output_root / ".staging" / output.name).exists()
    root = zarr.open_group(output, mode="r", zarr_format=3)
    assert root.metadata.zarr_format == 3
    assert root["surface"]["eastward_wind_10m"].shape == (2, 3, 4)
    assert root["surface"]["precipitation_flux"].attrs["standard_name"] == "precipitation_flux"
    assert "derived" not in root
    assert validate_structure(output, require_ready=True)["zarr_format"] == 3
    assert run_convert(config, reader=reader) == output


def test_plan_cache_reuses_unchanged_inspection_and_rejects_changed_manifest(
    tmp_path: Path,
) -> None:
    run_dir, reader = source_run(tmp_path)
    config = processor_config(tmp_path, run_dir)
    config_path = tmp_path / "job.yaml"
    config_path.write_text("test", encoding="utf-8")
    report, plan = build_plan(config, reader=reader)
    save_plan_cache(config_path, config, report, plan)

    cached = load_plan_cache(config_path, config)
    assert cached is not None
    assert cached[0].input_hash == report.input_hash
    assert cached[1].dataset_id == plan.dataset_id

    report.manifest_path.write_text("{}", encoding="utf-8")
    assert load_plan_cache(config_path, config) is None


def test_completed_ingestion_resume_does_not_decode_source_files(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    config = processor_config(tmp_path, run_dir)
    report, plan = build_plan(config, reader=reader)
    convert_messages(config, plan, report, reader=reader)
    calls = reader.calls

    convert_messages(config, plan, report, reader=reader)

    assert reader.calls == calls


def test_point_layout_preserves_values_masks_edges_and_2x2(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    # One missing source cell exercises packed fill/mask semantics through rechunking.
    reader.messages["gfs-2025010100-f003.grib2"][0].values[-1] = np.nan
    config = processor_config(tmp_path, run_dir).model_copy(
        update={"chunking": ChunkingConfig(access_pattern="point", point_spatial_chunk=32)}
    )
    output = run_convert(config, reader=reader)
    root = zarr.open_group(output, mode="r", zarr_format=3)
    array = root["surface"]["air_temperature_2m"]

    assert array.chunks == (2, 3, 4)
    block = np.asarray(array[:, -2:, -2:])
    assert block.shape == (2, 2, 2)
    assert block[1, -1, -1] == array.attrs["_FillValue"]
    assert np.isfinite(block[0]).all()


def test_point_rechunk_resumes_completed_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, reader = source_run(tmp_path)
    config = processor_config(tmp_path, run_dir).model_copy(
        update={"chunking": ChunkingConfig(access_pattern="point", point_spatial_chunk=32)}
    )
    report, plan = build_plan(config, reader=reader)
    convert_messages(config, plan, report, reader=reader)
    assembly = plan.staging_path.with_name(f"{plan.dataset_id}.rechunking.zarr")
    ForecastStore.create(assembly, plan, report, config)
    completed = plan.variables[0]
    ingestion = plan.staging_path.with_name(f"{plan.dataset_id}.ingest.zarr")
    _copy_variable(config, plan, ingestion, assembly, completed)

    copied: list[str] = []

    def record_copy(*args: object, **kwargs: object) -> str:
        variable = args[-1]
        assert hasattr(variable, "name")
        copied.append(str(variable.name))
        return _copy_variable(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("forecast_zarr.conversion._copy_variable", record_copy)
    assert assemble_final_store(config, plan, report) == plan.staging_path
    assert completed.name not in copied
    assert plan.staging_path.is_dir()


def test_layout_validation_rejects_legacy_point_chunks(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    config = processor_config(tmp_path, run_dir).model_copy(
        update={"chunking": ChunkingConfig(access_pattern="point", point_spatial_chunk=32)}
    )
    output = run_convert(config, reader=reader)
    _, plan = build_plan(config, reader=reader)
    variable = plan.variables[0]
    legacy = variable.layout.model_copy(update={"chunks": (1, 3, 4), "shards": (1, 3, 4)})
    bad_plan = plan.model_copy(
        update={"variables": (variable.model_copy(update={"layout": legacy}), *plan.variables[1:])}
    )
    with pytest.raises(ValidationError, match="wrong chunks"):
        validate_structure(output, bad_plan)


def test_failed_validation_never_publishes_ready_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, reader = source_run(tmp_path)
    config = processor_config(tmp_path, run_dir)
    _, plan = build_plan(config, reader=reader)

    def fail(*args: object, **kwargs: object) -> dict[str, object]:
        raise ValidationError("injected failure")

    monkeypatch.setattr("forecast_zarr.pipeline.validate_round_trip", fail)
    with pytest.raises(ValidationError, match="injected failure"):
        run_convert(config, reader=reader)
    assert not plan.output_path.exists()
    assert not (plan.staging_path / "READY.json").exists()


def test_incomplete_source_cycle_is_rejected_before_staging(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "downloading"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    config = processor_config(tmp_path, run_dir)
    with pytest.raises(InputContractError):
        run_convert(config, reader=reader)
    assert not (config.output_root / ".staging").exists()


def test_processing_manifest_has_portable_source_references(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    output = run_convert(processor_config(tmp_path, run_dir), reader=reader)
    document = json.loads(
        (output / "provenance" / "processing-manifest.json").read_text(encoding="utf-8")
    )
    assert document["input_manifest"] == "provenance/source-manifest.json"
    assert document["validation"]["round_trip"]["point_checks"] > 0
    assert document["critical_metadata_sha256"]


def test_instant_cloud_cover_wins_over_average_duplicate(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    for messages in reader.messages.values():
        first = messages[0]
        step = first.meta.forecast_step
        name = first.meta.file_name
        shape = (first.meta.nj, first.meta.ni)
        messages.extend(
            [
                decoded_message(
                    name,
                    "tcc",
                    step,
                    np.full(shape, 25.0),
                    level=0,
                    units="%",
                    type_of_level="atmosphere",
                    step_type="instant",
                    message_index=4,
                ),
                decoded_message(
                    name,
                    "tcc",
                    step,
                    np.full(shape, 60.0),
                    level=0,
                    units="%",
                    type_of_level="atmosphere",
                    step_type="avg",
                    message_index=5,
                ),
            ]
        )
    config = processor_config(tmp_path, run_dir)
    config = config.model_copy(update={"variables": (*config.variables, "cloud_area_fraction")})
    output = run_convert(config, reader=reader)
    root = zarr.open_group(output, mode="r", zarr_format=3)
    cloud = root["surface"]["cloud_area_fraction"]
    encoded = np.asarray(cloud[:])
    physical = encoded * cloud.attrs["scale_factor"] + cloud.attrs["add_offset"]
    assert np.allclose(physical, 0.25, atol=0.0001)


def test_prate_uses_instant_not_average_and_includes_f000(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    for messages in reader.messages.values():
        first = messages[0]
        step = first.meta.forecast_step
        name = first.meta.file_name
        shape = (first.meta.nj, first.meta.ni)
        messages.append(
            decoded_message(
                name,
                "prate",
                step,
                np.full(shape, 0.5),
                level=0,
                units="kg m-2 s-1",
                type_of_level="surface",
                step_type="avg",
                message_index=21,
                discipline=0,
                parameter_category=1,
                parameter_number=7,
            )
        )

    output = run_convert(processor_config(tmp_path, run_dir), reader=reader)
    root = zarr.open_group(output, mode="r", zarr_format=3)
    precipitation = root["surface"]["precipitation_flux"]
    encoded = np.asarray(precipitation[:])
    physical = encoded * precipitation.attrs["scale_factor"] + precipitation.attrs["add_offset"]

    assert np.isfinite(physical[0]).all()
    assert np.all(physical < 0.01)
    assert precipitation.attrs["cell_methods"] == "time: point"


def test_pwat_sidecar_with_same_forecast_step_merges_by_valid_time(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    name = "gfs-2025010100-f003-pwat.grib2"
    payload = b"synthetic-pwat-sidecar"
    (run_dir / name).write_bytes(payload)
    reader.messages[name] = [
        decoded_message(
            name,
            "pwat",
            3,
            np.full((3, 4), 20.0),
            level=0,
            units="kg m-2",
            type_of_level="atmosphereSingleLayer",
            message_index=0,
        )
    ]

    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "1.1"
    manifest["files"].append(
        {
            "name": name,
            "url": "https://example.invalid/pwat.grib2",
            "size": len(payload),
            "etag": None,
            "checksum": f"sha256:{hashlib.sha256(payload).hexdigest()}",
            "forecast_step": 3,
            "status": "validated",
            "completed_at": "2025-01-01T00:00:00+00:00",
        }
    )
    manifest["applied_plan"]["files"].append(
        {
            "name": name,
            "forecast_step": 3,
            "expected_parameters": ["pwat"],
            "expected_fields": [
                {
                    "short_name": "pwat",
                    "type_of_level": "atmosphereSingleLayer",
                    "level": "0",
                    "step_type": "instant",
                }
            ],
        }
    )
    manifest["variables"].append("precipitable_water")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    output = run_convert(processor_config(tmp_path, run_dir), reader=reader)
    root = zarr.open_group(output, mode="r", zarr_format=3)
    pwat = root["atmosphere"]["atmosphere_mass_content_of_water_vapor"]
    encoded = np.asarray(pwat[1, :, :])
    physical = encoded * pwat.attrs["scale_factor"] + pwat.attrs["add_offset"]

    assert np.allclose(physical, 20.0, atol=0.01)


def test_latest_precipitation_interval_wins_over_run_accumulation(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    messages = reader.messages["gfs-2025010100-f003.grib2"]
    shape = (messages[0].meta.nj, messages[0].meta.ni)
    messages.extend(
        [
            decoded_message(
                "gfs-2025010100-f003.grib2",
                "tp",
                3,
                np.full(shape, 1.5),
                level=0,
                units="kg m-2",
                type_of_level="surface",
                step_type="accum",
                start_step=2,
                end_step=3,
                message_index=4,
            ),
            decoded_message(
                "gfs-2025010100-f003.grib2",
                "tp",
                3,
                np.full(shape, 7.0),
                level=0,
                units="kg m-2",
                type_of_level="surface",
                step_type="accum",
                start_step=0,
                end_step=3,
                message_index=5,
            ),
        ]
    )
    config = processor_config(tmp_path, run_dir)
    config = config.model_copy(update={"variables": (*config.variables, "precipitation_amount")})
    output = run_convert(config, reader=reader)
    root = zarr.open_group(output, mode="r", zarr_format=3)
    precipitation = root["surface"]["precipitation_amount"]
    encoded = np.asarray(precipitation[1, :, :])
    physical = encoded * precipitation.attrs["scale_factor"] + precipitation.attrs["add_offset"]
    assert np.allclose(physical, 1.5, atol=0.01)
    assert precipitation.attrs["cell_methods"] == "time: sum"


def test_real_eccodes_grib_round_trip(tmp_path: Path) -> None:
    run_dir = real_grib_source_run(tmp_path)
    output = run_convert(processor_config(tmp_path, run_dir))
    ready = json.loads((output / "READY.json").read_text(encoding="utf-8"))
    assert ready["software_versions"]["eccodes"]
    assert ready["status"] == "ready"
    assert validate_structure(output, require_ready=True)["zarr_format"] == 3


def test_all_source_energy_fields_are_written_without_derived_group(tmp_path: Path) -> None:
    run_dir, reader = energy_source_run(tmp_path)
    variables = (
        "eastward_wind_10m",
        "northward_wind_10m",
        "eastward_wind_80m",
        "northward_wind_80m",
        "eastward_wind_100m",
        "northward_wind_100m",
        "air_temperature_80m",
        "air_temperature_100m",
        "specific_humidity_80m",
        "air_pressure_80m",
        "atmosphere_boundary_layer_thickness",
    )
    config = processor_config(tmp_path, run_dir).model_copy(
        update={"variables": variables, "required_variables": variables}
    )

    output = run_convert(config, reader=reader)
    root = zarr.open_group(output, mode="r", zarr_format=3)

    assert "eastward_wind_80m" in root["height_80m"]
    assert "air_temperature_100m" in root["height_100m"]
    assert "atmosphere_boundary_layer_thickness" in root["atmosphere"]
    assert "derived" not in root
