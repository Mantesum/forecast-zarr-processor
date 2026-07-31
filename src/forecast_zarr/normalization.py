"""Provider-neutral names, units, grids, and safe compact encodings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

from forecast_zarr.models import ArrayEncoding

VariableGroup = Literal["surface", "height_80m", "height_100m", "atmosphere", "derived"]


@dataclass(frozen=True)
class VariableSpec:
    name: str
    short_names: frozenset[str]
    type_of_level: str | None
    level: float | None
    units: str
    standard_name: str | None
    long_name: str
    compact_precision: float
    valid_range: tuple[float, float] | None = None
    accepted_step_types: frozenset[str] | None = None
    group: VariableGroup = "surface"
    grib2_codes: frozenset[tuple[int, int, int]] | None = None


SPECS: tuple[VariableSpec, ...] = (
    VariableSpec(
        "air_temperature_2m",
        frozenset({"2t", "t"}),
        "heightAboveGround",
        2,
        "K",
        "air_temperature",
        "2 metre air temperature",
        0.01,
        (150, 350),
    ),
    VariableSpec(
        "relative_humidity_2m",
        frozenset({"2r", "r"}),
        "heightAboveGround",
        2,
        "%",
        "relative_humidity",
        "2 metre relative humidity",
        0.01,
        (0, 100),
    ),
    VariableSpec(
        "dew_point_temperature_2m",
        frozenset({"2d", "dpt"}),
        "heightAboveGround",
        2,
        "K",
        "dew_point_temperature",
        "2 metre dew-point temperature",
        0.01,
        (150, 350),
    ),
    VariableSpec(
        "air_pressure_at_mean_sea_level",
        frozenset({"msl", "prmsl"}),
        None,
        None,
        "Pa",
        "air_pressure_at_mean_sea_level",
        "Mean sea-level pressure",
        1,
        (80_000, 110_000),
    ),
    VariableSpec(
        "surface_air_pressure",
        frozenset({"sp"}),
        "surface",
        0,
        "Pa",
        "surface_air_pressure",
        "Surface air pressure",
        1,
        (50_000, 110_000),
    ),
    VariableSpec(
        "eastward_wind_10m",
        frozenset({"10u", "u"}),
        "heightAboveGround",
        10,
        "m s-1",
        "eastward_wind",
        "10 metre eastward wind",
        0.01,
        (-150, 150),
    ),
    VariableSpec(
        "northward_wind_10m",
        frozenset({"10v", "v"}),
        "heightAboveGround",
        10,
        "m s-1",
        "northward_wind",
        "10 metre northward wind",
        0.01,
        (-150, 150),
    ),
    VariableSpec(
        "eastward_wind_80m",
        frozenset({"u"}),
        "heightAboveGround",
        80,
        "m s-1",
        "eastward_wind",
        "80 metre eastward wind",
        0.01,
        (-150, 150),
        group="height_80m",
    ),
    VariableSpec(
        "northward_wind_80m",
        frozenset({"v"}),
        "heightAboveGround",
        80,
        "m s-1",
        "northward_wind",
        "80 metre northward wind",
        0.01,
        (-150, 150),
        group="height_80m",
    ),
    VariableSpec(
        "eastward_wind_100m",
        frozenset({"100u", "u"}),
        "heightAboveGround",
        100,
        "m s-1",
        "eastward_wind",
        "100 metre eastward wind",
        0.01,
        (-150, 150),
        group="height_100m",
    ),
    VariableSpec(
        "northward_wind_100m",
        frozenset({"100v", "v"}),
        "heightAboveGround",
        100,
        "m s-1",
        "northward_wind",
        "100 metre northward wind",
        0.01,
        (-150, 150),
        group="height_100m",
    ),
    VariableSpec(
        "air_temperature_80m",
        frozenset({"t"}),
        "heightAboveGround",
        80,
        "K",
        "air_temperature",
        "80 metre air temperature",
        0.01,
        (150, 350),
        group="height_80m",
    ),
    VariableSpec(
        "specific_humidity_80m",
        frozenset({"q"}),
        "heightAboveGround",
        80,
        "kg kg-1",
        "specific_humidity",
        "80 metre specific humidity",
        0.000001,
        (0, 0.1),
        group="height_80m",
    ),
    VariableSpec(
        "air_pressure_80m",
        frozenset({"pres"}),
        "heightAboveGround",
        80,
        "Pa",
        "air_pressure",
        "80 metre air pressure",
        1,
        (40_000, 110_000),
        group="height_80m",
    ),
    VariableSpec(
        "air_temperature_100m",
        frozenset({"t"}),
        "heightAboveGround",
        100,
        "K",
        "air_temperature",
        "100 metre air temperature",
        0.01,
        (150, 350),
        group="height_100m",
    ),
    VariableSpec(
        "wind_speed_10m",
        frozenset(),
        None,
        None,
        "m s-1",
        "wind_speed",
        "10 metre wind speed",
        0.01,
        (0, 150),
        group="derived",
    ),
    VariableSpec(
        "wind_speed_80m",
        frozenset(),
        None,
        None,
        "m s-1",
        "wind_speed",
        "80 metre wind speed",
        0.01,
        (0, 150),
        group="derived",
    ),
    VariableSpec(
        "wind_speed_100m",
        frozenset(),
        None,
        None,
        "m s-1",
        "wind_speed",
        "100 metre wind speed",
        0.01,
        (0, 150),
        group="derived",
    ),
    VariableSpec(
        "wind_from_direction_10m",
        frozenset(),
        None,
        None,
        "degree",
        "wind_from_direction",
        "10 metre meteorological wind-from direction",
        0.1,
        (0, 360),
        group="derived",
    ),
    VariableSpec(
        "wind_from_direction_80m",
        frozenset(),
        None,
        None,
        "degree",
        "wind_from_direction",
        "80 metre meteorological wind-from direction",
        0.1,
        (0, 360),
        group="derived",
    ),
    VariableSpec(
        "wind_from_direction_100m",
        frozenset(),
        None,
        None,
        "degree",
        "wind_from_direction",
        "100 metre meteorological wind-from direction",
        0.1,
        (0, 360),
        group="derived",
    ),
    VariableSpec(
        "relative_humidity_80m",
        frozenset(),
        None,
        None,
        "%",
        "relative_humidity",
        "80 metre relative humidity derived from T, q, and p",
        0.01,
        (0, 150),
        group="derived",
    ),
    VariableSpec(
        "air_density_80m",
        frozenset(),
        None,
        None,
        "kg m-3",
        "air_density",
        "80 metre moist-air density",
        0.001,
        (0.5, 1.7),
        group="derived",
    ),
    VariableSpec(
        "wind_shear_exponent_10m_100m",
        frozenset(),
        None,
        None,
        "1",
        None,
        "Power-law wind shear exponent between 10 and 100 metres",
        0.001,
        (-2, 2),
        group="derived",
    ),
    VariableSpec(
        "wind_power_density_100m",
        frozenset(),
        None,
        None,
        "W m-2",
        None,
        "100 metre wind power density using 80 metre moist-air density",
        1,
        None,
        group="derived",
    ),
    VariableSpec(
        "wind_speed_of_gust",
        frozenset({"gust"}),
        "surface",
        0,
        "m s-1",
        "wind_speed_of_gust",
        "Surface wind speed of gust",
        0.01,
        (0, 200),
    ),
    VariableSpec(
        "atmosphere_boundary_layer_thickness",
        frozenset({"unknown"}),
        "surface",
        0,
        "m",
        "atmosphere_boundary_layer_thickness",
        "Planetary boundary-layer height",
        1,
        (0, 10_000),
        group="atmosphere",
        grib2_codes=frozenset({(0, 3, 196)}),
    ),
    VariableSpec(
        "friction_velocity",
        frozenset({"fricv"}),
        "surface",
        0,
        "m s-1",
        None,
        "Surface friction velocity",
        0.001,
        (0, 10),
    ),
    VariableSpec(
        "surface_roughness_length",
        frozenset({"fsr"}),
        "surface",
        0,
        "m",
        "surface_roughness_length",
        "Forecast surface roughness length",
        0.001,
        (0, 20),
    ),
    VariableSpec(
        "precipitation_amount",
        frozenset({"tp"}),
        None,
        None,
        "kg m-2",
        "precipitation_amount",
        "Accumulated precipitation amount",
        0.01,
        (0, 1000),
        frozenset({"accum"}),
    ),
    VariableSpec(
        "cloud_area_fraction",
        frozenset({"tcc"}),
        None,
        None,
        "1",
        "cloud_area_fraction",
        "Total cloud area fraction",
        0.0001,
        (0, 1),
        frozenset({"instant"}),
    ),
    VariableSpec(
        "low_cloud_area_fraction",
        frozenset({"lcc", "avg_lcc"}),
        "lowCloudLayer",
        0,
        "1",
        None,
        "Low cloud area fraction",
        0.0001,
        (0, 1),
        frozenset({"instant"}),
        group="atmosphere",
    ),
    VariableSpec(
        "medium_cloud_area_fraction",
        frozenset({"mcc", "avg_mcc"}),
        "middleCloudLayer",
        0,
        "1",
        None,
        "Middle cloud area fraction",
        0.0001,
        (0, 1),
        frozenset({"instant"}),
        group="atmosphere",
    ),
    VariableSpec(
        "high_cloud_area_fraction",
        frozenset({"hcc", "avg_hcc"}),
        "highCloudLayer",
        0,
        "1",
        None,
        "High cloud area fraction",
        0.0001,
        (0, 1),
        frozenset({"instant"}),
        group="atmosphere",
    ),
    VariableSpec(
        "visibility_in_air",
        frozenset({"vis"}),
        None,
        None,
        "m",
        "visibility_in_air",
        "Horizontal visibility",
        1,
        (0, 100_000),
    ),
    VariableSpec(
        "surface_downwelling_shortwave_flux_in_air",
        frozenset({"sdswrf"}),
        None,
        None,
        "W m-2",
        "surface_downwelling_shortwave_flux_in_air",
        "Surface downwelling shortwave radiation",
        0.1,
        (0, 2000),
        frozenset({"avg"}),
    ),
    VariableSpec(
        "surface_upwelling_shortwave_flux_in_air",
        frozenset({"suswrf"}),
        "surface",
        0,
        "W m-2",
        "surface_upwelling_shortwave_flux_in_air",
        "Surface upwelling shortwave radiation flux",
        0.1,
        (-100, 2000),
        frozenset({"avg"}),
    ),
    VariableSpec(
        "surface_downwelling_longwave_flux_in_air",
        frozenset({"sdlwrf"}),
        "surface",
        0,
        "W m-2",
        "surface_downwelling_longwave_flux_in_air",
        "Surface downwelling longwave radiation flux",
        0.1,
        (0, 1000),
        frozenset({"avg"}),
    ),
    VariableSpec(
        "surface_albedo",
        frozenset({"avg_al"}),
        "surface",
        0,
        "1",
        "surface_albedo",
        "Time-mean forecast surface albedo",
        0.0001,
        (0, 1),
        frozenset({"avg"}),
    ),
    VariableSpec(
        "atmosphere_mass_content_of_water_vapor",
        frozenset({"pwat"}),
        "atmosphereSingleLayer",
        0,
        "kg m-2",
        "atmosphere_mass_content_of_water_vapor",
        "Total atmospheric precipitable water",
        0.01,
        (0, 150),
        group="atmosphere",
    ),
    VariableSpec(
        "surface_snow_thickness",
        frozenset({"sde"}),
        "surface",
        0,
        "m",
        "surface_snow_thickness",
        "Surface snow depth",
        0.001,
        (0, 20),
    ),
    VariableSpec(
        "snow_water_equivalent",
        frozenset({"sdwe"}),
        "surface",
        0,
        "kg m-2",
        None,
        "Water equivalent of accumulated snow depth",
        0.1,
        (0, 10_000),
    ),
    VariableSpec(
        "surface_altitude",
        frozenset({"orog", "z", "gh"}),
        None,
        None,
        "m",
        "surface_altitude",
        "Surface altitude",
        0.1,
        (-500, 10_000),
    ),
    VariableSpec(
        "weather_code",
        frozenset({"wcode", "weathercode"}),
        None,
        None,
        "1",
        None,
        "Provider weather code",
        1,
        (0, 255),
    ),
)

SPECS_BY_NAME = {spec.name: spec for spec in SPECS}

DERIVED_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "wind_speed_10m": ("eastward_wind_10m", "northward_wind_10m"),
    "wind_speed_80m": ("eastward_wind_80m", "northward_wind_80m"),
    "wind_speed_100m": ("eastward_wind_100m", "northward_wind_100m"),
    "wind_from_direction_10m": ("eastward_wind_10m", "northward_wind_10m"),
    "wind_from_direction_80m": ("eastward_wind_80m", "northward_wind_80m"),
    "wind_from_direction_100m": ("eastward_wind_100m", "northward_wind_100m"),
    "relative_humidity_80m": (
        "air_temperature_80m",
        "specific_humidity_80m",
        "air_pressure_80m",
    ),
    "air_density_80m": (
        "air_temperature_80m",
        "specific_humidity_80m",
        "air_pressure_80m",
    ),
    "wind_shear_exponent_10m_100m": (
        "eastward_wind_10m",
        "northward_wind_10m",
        "eastward_wind_100m",
        "northward_wind_100m",
    ),
    "wind_power_density_100m": (
        "eastward_wind_100m",
        "northward_wind_100m",
        "air_temperature_80m",
        "specific_humidity_80m",
        "air_pressure_80m",
    ),
}


def accepts_step_type(spec: VariableSpec, step_type: str) -> bool:
    """Return whether a GRIB statistical field matches the variable's semantics."""
    return spec.accepted_step_types is None or step_type in spec.accepted_step_types


def match_variable(
    short_name: str,
    type_of_level: str,
    level: float,
    discipline: int | None = None,
    parameter_category: int | None = None,
    parameter_number: int | None = None,
) -> VariableSpec | None:
    """Resolve an ecCodes parameter/level tuple without provider-specific branches."""
    for spec in SPECS:
        if short_name not in spec.short_names:
            continue
        if spec.type_of_level is not None and spec.type_of_level != type_of_level:
            continue
        if spec.level is not None and not np.isclose(spec.level, level):
            continue
        if spec.grib2_codes is not None and (
            discipline is None
            or parameter_category is None
            or parameter_number is None
            or (discipline, parameter_category, parameter_number) not in spec.grib2_codes
        ):
            continue
        return spec
    return None


def normalize_values(
    spec: VariableSpec,
    values: npt.NDArray[np.float64],
    source_units: str,
) -> npt.NDArray[np.float64]:
    """Convert the few known provider unit differences into canonical units."""
    result = values.astype(np.float64, copy=True)
    normalized_units = source_units.strip().lower().replace("**", "^")
    fraction_names = {
        "cloud_area_fraction",
        "low_cloud_area_fraction",
        "medium_cloud_area_fraction",
        "high_cloud_area_fraction",
        "surface_albedo",
    }
    if spec.name in fraction_names and normalized_units in {"%", "percent"}:
        result /= 100
    elif spec.name == "precipitation_amount" and normalized_units in {"m", "metres", "meters"}:
        result *= 1000
    elif spec.name == "surface_altitude" and short_unit_is_geopotential(source_units):
        result /= 9.80665
    return result


def short_unit_is_geopotential(units: str) -> bool:
    compact = units.lower().replace(" ", "")
    return compact in {"m^2s^-2", "m2s-2", "m**2s**-2"}


def normalize_longitudes(
    values: npt.NDArray[np.float64], convention: str
) -> npt.NDArray[np.float64]:
    normalized = (values + 180) % 360 - 180 if convention == "-180_180" else values % 360
    return np.where(np.isclose(normalized, 0), 0.0, normalized)


def regular_grid(
    latitudes: npt.NDArray[np.float64],
    longitudes: npt.NDArray[np.float64],
    values: npt.NDArray[np.float64],
    *,
    convention: str,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Map any ecCodes scanning order to ascending latitude/longitude axes."""
    lat = np.round(latitudes.astype(np.float64), 10)
    lon = np.round(normalize_longitudes(longitudes.astype(np.float64), convention), 10)
    lat_axis = np.unique(lat)
    lon_axis = np.unique(lon)
    if lat_axis.size * lon_axis.size != values.size:
        raise ValueError("message coordinates do not form a complete regular grid")
    result = np.full((lat_axis.size, lon_axis.size), np.nan, dtype=np.float64)
    result[np.searchsorted(lat_axis, lat), np.searchsorted(lon_axis, lon)] = values
    return lat_axis, lon_axis, result


def compact_encoding(
    spec: VariableSpec, minimum: float | None, maximum: float | None
) -> ArrayEncoding:
    """Choose int16 only when the observed range fits the documented error bound."""
    if minimum is None or maximum is None or not np.isfinite([minimum, maximum]).all():
        return ArrayEncoding(
            dtype="float32",
            fill_value=float("nan"),
            maximum_absolute_error=0,
            fallback_reason="no_finite_range",
        )
    scale = spec.compact_precision * 2
    midpoint = (minimum + maximum) / 2
    required_codes = (maximum - minimum) / scale
    if required_codes > 65_532:
        return ArrayEncoding(
            dtype="float32",
            fill_value=float("nan"),
            maximum_absolute_error=0,
            fallback_reason="range_exceeds_int16_at_required_precision",
        )
    return ArrayEncoding(
        dtype="int16",
        fill_value=-32768,
        scale_factor=scale,
        add_offset=midpoint,
        maximum_absolute_error=spec.compact_precision,
    )


def encode_values(
    values: npt.NDArray[np.float64], encoding: ArrayEncoding
) -> npt.NDArray[np.int16] | npt.NDArray[np.float32]:
    """Encode with explicit overflow checks; never wrap integer values."""
    if encoding.dtype == "float32":
        return values.astype(np.float32)
    assert encoding.scale_factor is not None
    assert encoding.add_offset is not None
    finite = np.isfinite(values)
    rounded = np.rint((values[finite] - encoding.add_offset) / encoding.scale_factor)
    if rounded.size and (rounded.min() < -32767 or rounded.max() > 32767):
        raise OverflowError("values overflow planned int16 encoding")
    result = np.full(values.shape, -32768, dtype=np.int16)
    result[finite] = rounded.astype(np.int16)
    return result


def decode_values(
    values: npt.NDArray[np.generic], encoding: ArrayEncoding
) -> npt.NDArray[np.float64]:
    if encoding.dtype == "float32":
        return values.astype(np.float64)
    assert encoding.scale_factor is not None
    assert encoding.add_offset is not None
    decoded = values.astype(np.float64) * encoding.scale_factor + encoding.add_offset
    decoded[values == encoding.fill_value] = np.nan
    return decoded
