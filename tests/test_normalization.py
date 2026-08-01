from __future__ import annotations

import numpy as np
import pytest

from forecast_zarr.normalization import (
    SPECS_BY_NAME,
    compact_encoding,
    decode_values,
    encode_values,
    match_variable,
    normalize_longitudes,
    regular_grid,
)


def test_longitudes_and_scanning_order_are_normalized() -> None:
    lat = np.asarray([1, 1, 0, 0], dtype=np.float64)
    lon = np.asarray([359, 0, 359, 0], dtype=np.float64)
    values = np.asarray([10, 11, 20, 21], dtype=np.float64)
    y, x, grid = regular_grid(lat, lon, values, convention="-180_180")
    assert y.tolist() == [0, 1]
    assert x.tolist() == [-1, 0]
    assert grid.tolist() == [[20, 21], [10, 11]]
    assert normalize_longitudes(np.asarray([0.0, 360.0]), "-180_180").tolist() == [0, 0]


def test_compact_encoding_respects_error_bound() -> None:
    encoding = compact_encoding(SPECS_BY_NAME["air_temperature_2m"], 250, 310)
    values = np.asarray([[273.156, np.nan, 301.239]], dtype=np.float64)
    decoded = decode_values(encode_values(values, encoding), encoding)
    assert np.allclose(decoded, values, atol=0.01, equal_nan=True)


def test_integer_overflow_is_never_silent() -> None:
    encoding = compact_encoding(SPECS_BY_NAME["eastward_wind_10m"], -1, 1)
    with pytest.raises(OverflowError):
        encode_values(np.asarray([1e9], dtype=np.float64), encoding)


def test_boundary_layer_height_uses_native_grib2_identity() -> None:
    assert match_variable("unknown", "surface", 0) is None
    matched = match_variable("unknown", "surface", 0, 0, 3, 196)
    assert matched is not None
    assert matched.name == "atmosphere_boundary_layer_thickness"


def test_prate_uses_exact_native_identity_and_canonical_name() -> None:
    matched = match_variable("prate", "surface", 0, 0, 1, 7)
    assert matched is not None
    assert matched.name == "precipitation_flux"
    assert match_variable("prate", "surface", 0) is None


def test_fields_absent_from_forecast_ingest_0_2_1_are_not_mapped() -> None:
    assert match_variable("2sh", "heightAboveGround", 2) is None
    assert match_variable("t", "surface", 0) is None
    assert match_variable("r", "atmosphereSingleLayer", 0) is None


def test_catalogue_contains_no_calculated_variables() -> None:
    calculated = {
        "wind_speed_10m",
        "wind_speed_80m",
        "wind_speed_100m",
        "wind_from_direction_10m",
        "wind_from_direction_80m",
        "wind_from_direction_100m",
        "relative_humidity_80m",
        "air_density_80m",
        "wind_shear_exponent_10m_100m",
        "wind_power_density_100m",
    }
    assert calculated.isdisjoint(SPECS_BY_NAME)
