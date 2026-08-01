from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import zarr

from forecast_zarr.pipeline import run_convert
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
