from __future__ import annotations

from collections import Counter
from pathlib import Path

from forecast_zarr.config import FULL_ENERGY_VARIABLES, load_config
from forecast_zarr.normalization import SPECS_BY_NAME
from forecast_zarr.status import status_report


def test_config_paths_are_relative_to_yaml(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "test.yaml"
    path.write_text("input_run: ../raw\noutput_root: ../zarr\n", encoding="utf-8")
    config = load_config(path)
    assert config.input_run == (tmp_path / "raw").resolve()
    assert config.output_root == (tmp_path / "zarr").resolve()


def test_distributed_processor_configs_load() -> None:
    config_dir = Path(__file__).parents[1] / "configs"
    for name in ("gfs-projecteol.yaml", "aifs-global-light.yaml", "renewable-energy.yaml"):
        config = load_config(config_dir / name)
        assert config.longitude_convention == "-180_180"


def test_global_energy_configs_load() -> None:
    config_dir = Path(__file__).parents[1] / "configs"
    names = (
        "gfs-global-weather-10day.yaml",
        "gfs-global-wind-energy-10day.yaml",
        "gfs-global-solar-energy-10day.yaml",
        "gfs-global-full-energy-10day.yaml",
    )
    loaded = {name: load_config(config_dir / name) for name in names}
    assert loaded[names[-1]].variables == FULL_ENERGY_VARIABLES
    assert all(config.longitude_convention == "-180_180" for config in loaded.values())


def test_full_energy_contract_is_exactly_34_source_arrays() -> None:
    expected = {
        "air_temperature_2m",
        "relative_humidity_2m",
        "dew_point_temperature_2m",
        "air_pressure_at_mean_sea_level",
        "surface_air_pressure",
        "eastward_wind_10m",
        "northward_wind_10m",
        "cloud_area_fraction",
        "precipitation_amount",
        "precipitation_flux",
        "visibility_in_air",
        "surface_downwelling_shortwave_flux_in_air",
        "surface_altitude",
        "wind_speed_of_gust",
        "friction_velocity",
        "surface_roughness_length",
        "surface_upwelling_shortwave_flux_in_air",
        "surface_downwelling_longwave_flux_in_air",
        "surface_albedo",
        "surface_snow_thickness",
        "snow_water_equivalent",
        "eastward_wind_80m",
        "northward_wind_80m",
        "air_temperature_80m",
        "specific_humidity_80m",
        "air_pressure_80m",
        "eastward_wind_100m",
        "northward_wind_100m",
        "air_temperature_100m",
        "atmosphere_boundary_layer_thickness",
        "low_cloud_area_fraction",
        "medium_cloud_area_fraction",
        "high_cloud_area_fraction",
        "atmosphere_mass_content_of_water_vapor",
    }
    assert len(FULL_ENERGY_VARIABLES) == 34
    assert set(FULL_ENERGY_VARIABLES) == expected
    assert Counter(SPECS_BY_NAME[name].group for name in FULL_ENERGY_VARIABLES) == {
        "surface": 21,
        "height_80m": 5,
        "height_100m": 3,
        "atmosphere": 5,
    }


def test_empty_status_is_healthy(tmp_path: Path) -> None:
    result = status_report(tmp_path / "zarr")
    assert result["status"] == "healthy"
    assert result["ready_count"] == 0
