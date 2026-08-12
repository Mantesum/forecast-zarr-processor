"""Strict YAML configuration with conservative server defaults."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from forecast_zarr.errors import ConfigurationError


class EncodingMode(StrEnum):
    LOSSLESS = "lossless"
    API_COMPACT = "api_compact"


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_budget_gib: float = Field(default=8, gt=0, le=8)
    max_workers: int = Field(default=2, ge=1, le=2)


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_budget_gib: float = Field(default=40, gt=0)
    min_free_gib: float = Field(default=10, ge=0)
    max_zarr_output_gib: float = Field(default=26, gt=0)
    max_temporary_gib: float = Field(default=6, gt=0)

    @model_validator(mode="after")
    def within_total_budget(self) -> StorageConfig:
        if self.max_zarr_output_gib + self.max_temporary_gib > self.total_budget_gib:
            raise ValueError("output and temporary budgets exceed total_budget_gib")
        return self


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_shard_mib: float = Field(default=8, ge=4, le=16)
    time_chunk: int = Field(default=1, ge=1, le=6)
    time_shard: int = Field(default=6, ge=1, le=24)
    min_spatial_chunk: int = Field(default=90, ge=16)
    max_spatial_chunk: int = Field(default=360, ge=32)
    max_spatial_shard: int = Field(default=720, ge=64)
    access_pattern: Literal["map", "point"] = "map"
    point_spatial_chunk: int = Field(default=32, ge=24, le=48)


class ValidationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    random_seed: int = 20250308
    point_samples: int = Field(default=24, ge=1, le=1000)
    bbox_samples: int = Field(default=4, ge=1, le=100)


WEATHER_VARIABLES = (
    "air_temperature_2m",
    "relative_humidity_2m",
    "dew_point_temperature_2m",
    "air_pressure_at_mean_sea_level",
    "surface_air_pressure",
    "eastward_wind_10m",
    "northward_wind_10m",
    "precipitation_amount",
    "precipitation_flux",
    "cloud_area_fraction",
    "visibility_in_air",
    "surface_downwelling_shortwave_flux_in_air",
    "surface_altitude",
)

WIND_ENERGY_VARIABLES = (
    "eastward_wind_10m",
    "northward_wind_10m",
    "eastward_wind_80m",
    "northward_wind_80m",
    "eastward_wind_100m",
    "northward_wind_100m",
    "air_temperature_2m",
    "air_temperature_80m",
    "air_temperature_100m",
    "specific_humidity_80m",
    "air_pressure_80m",
    "surface_air_pressure",
    "air_pressure_at_mean_sea_level",
    "wind_speed_of_gust",
    "atmosphere_boundary_layer_thickness",
    "friction_velocity",
    "surface_roughness_length",
    "precipitation_amount",
    "surface_altitude",
)

SOLAR_ENERGY_VARIABLES = (
    "surface_downwelling_shortwave_flux_in_air",
    "surface_upwelling_shortwave_flux_in_air",
    "surface_downwelling_longwave_flux_in_air",
    "cloud_area_fraction",
    "low_cloud_area_fraction",
    "medium_cloud_area_fraction",
    "high_cloud_area_fraction",
    "air_temperature_2m",
    "eastward_wind_10m",
    "northward_wind_10m",
    "relative_humidity_2m",
    "dew_point_temperature_2m",
    "surface_albedo",
    "atmosphere_mass_content_of_water_vapor",
    "precipitation_amount",
    "surface_snow_thickness",
    "snow_water_equivalent",
    "surface_air_pressure",
    "surface_altitude",
)

FULL_ENERGY_VARIABLES = tuple(
    dict.fromkeys((*WEATHER_VARIABLES, *WIND_ENERGY_VARIABLES, *SOLAR_ENERGY_VARIABLES))
)

VARIABLE_PROFILES = {
    "weather": WEATHER_VARIABLES,
    "wind_energy": WIND_ENERGY_VARIABLES,
    "solar_energy": SOLAR_ENERGY_VARIABLES,
    "full_energy": FULL_ENERGY_VARIABLES,
}

DEFAULT_VARIABLES = WEATHER_VARIABLES


class ProcessorConfig(BaseModel):
    """One deterministic processing request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_run: Path
    output_root: Path = Path("data/zarr")
    encoding: EncodingMode = EncodingMode.API_COMPACT
    longitude_convention: Literal["-180_180", "0_360"] = "-180_180"
    variables: tuple[str, ...] = DEFAULT_VARIABLES
    required_variables: tuple[str, ...] = ()
    crop_to_manifest_regions: bool = True
    resume: bool = True
    compression_level: int = Field(default=7, ge=-7, le=22)
    runtime: RuntimeConfig = RuntimeConfig()
    storage: StorageConfig = StorageConfig()
    chunking: ChunkingConfig = ChunkingConfig()
    validation: ValidationConfig = ValidationConfig()

    @model_validator(mode="after")
    def unique_and_required_selected(self) -> ProcessorConfig:
        if len(self.variables) != len(set(self.variables)):
            raise ValueError("variables must be unique")
        missing = set(self.required_variables) - set(self.variables)
        if missing:
            raise ValueError(f"required variables are not selected: {sorted(missing)}")
        return self


def load_config(path: Path) -> ProcessorConfig:
    """Read and validate a processor YAML document."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("configuration root must be an object")
        config = ProcessorConfig.model_validate(raw)
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise ConfigurationError(f"invalid configuration {path}: {error}") from error
    base = path.resolve().parent
    input_run = config.input_run
    output_root = config.output_root
    return config.model_copy(
        update={
            "input_run": input_run if input_run.is_absolute() else (base / input_run).resolve(),
            "output_root": output_root
            if output_root.is_absolute()
            else (base / output_root).resolve(),
        }
    )
