"""Provider-neutral names, units, grids, and safe compact encodings."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from forecast_zarr.models import ArrayEncoding


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
        "eastward_wind_100m",
        frozenset({"100u", "u"}),
        "heightAboveGround",
        100,
        "m s-1",
        "eastward_wind",
        "100 metre eastward wind",
        0.01,
        (-150, 150),
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


def match_variable(short_name: str, type_of_level: str, level: float) -> VariableSpec | None:
    """Resolve an ecCodes parameter/level tuple without provider-specific branches."""
    for spec in SPECS:
        if short_name not in spec.short_names:
            continue
        if spec.type_of_level is not None and spec.type_of_level != type_of_level:
            continue
        if spec.level is not None and not np.isclose(spec.level, level):
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
    if spec.name == "cloud_area_fraction" and normalized_units in {"%", "percent"}:
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
