from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import zarr

from forecast_zarr.conversion import _calculate_derived
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
    speed = np.asarray(root["derived"]["wind_speed_10m"][0, :, :])
    assert np.isfinite(speed).all()
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
                    message_index=3,
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
                    message_index=4,
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
                message_index=3,
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
                message_index=4,
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


def test_energy_fields_and_derived_wind_are_written_to_separate_groups(tmp_path: Path) -> None:
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
        "wind_speed_80m",
        "wind_from_direction_100m",
        "relative_humidity_80m",
        "air_density_80m",
        "wind_shear_exponent_10m_100m",
        "wind_power_density_100m",
    )
    config = processor_config(tmp_path, run_dir).model_copy(
        update={"variables": variables, "required_variables": variables}
    )

    output = run_convert(config, reader=reader)
    root = zarr.open_group(output, mode="r", zarr_format=3)

    assert "eastward_wind_80m" in root["height_80m"]
    assert "air_temperature_100m" in root["height_100m"]
    assert "atmosphere_boundary_layer_thickness" in root["atmosphere"]
    for name in (
        "wind_speed_80m",
        "wind_from_direction_100m",
        "relative_humidity_80m",
        "air_density_80m",
        "wind_shear_exponent_10m_100m",
        "wind_power_density_100m",
    ):
        assert np.isfinite(np.asarray(root["derived"][name][:])).all()


def test_derived_formula_semantics() -> None:
    east = np.asarray([[1.0]], dtype=np.float64)
    north = np.asarray([[0.0]], dtype=np.float64)
    direction = _calculate_derived(
        "wind_from_direction_10m",
        {"eastward_wind_10m": east, "northward_wind_10m": north},
    )
    assert direction.item() == 270

    thermodynamics = {
        "air_temperature_80m": np.asarray([[280.0]]),
        "specific_humidity_80m": np.asarray([[0.006]]),
        "air_pressure_80m": np.asarray([[99_000.0]]),
    }
    humidity = _calculate_derived("relative_humidity_80m", thermodynamics)
    density = _calculate_derived("air_density_80m", thermodynamics)
    assert 90 < humidity.item() < 100
    assert 1.1 < density.item() < 1.4
