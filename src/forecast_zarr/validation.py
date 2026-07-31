"""Structural, semantic, and sampled GRIB/Zarr round-trip validation."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, cast

import numpy as np
import zarr

from forecast_zarr.config import ProcessorConfig
from forecast_zarr.errors import ValidationError
from forecast_zarr.grib import EccodesReader, GribReader
from forecast_zarr.models import InspectionReport, ProcessingPlan
from forecast_zarr.normalization import (
    SPECS_BY_NAME,
    accepts_step_type,
    decode_values,
    match_variable,
    normalize_values,
    regular_grid,
)


def validate_structure(
    path: Path,
    plan: ProcessingPlan | None = None,
    *,
    require_ready: bool = True,
) -> dict[str, Any]:
    """Validate Zarr v3 metadata, coordinates, dimensions, and physical ranges."""
    metadata_path = path / "zarr.json"
    if not metadata_path.is_file():
        raise ValidationError("root zarr.json is missing")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"invalid root zarr.json: {error}") from error
    if metadata.get("zarr_format") != 3 or metadata.get("node_type") != "group":
        raise ValidationError("store is not a Zarr v3 group")
    if require_ready and not (path / "READY.json").is_file():
        raise ValidationError("READY.json is missing")
    root = zarr.open_group(store=path, mode="r", zarr_format=3)
    try:
        coordinates = cast(zarr.Group, root["coordinates"])
        latitude_array = cast(zarr.Array[Any], coordinates["latitude"])
        longitude_array = cast(zarr.Array[Any], coordinates["longitude"])
        valid_time_array = cast(zarr.Array[Any], coordinates["valid_time"])
        latitude = np.asarray(latitude_array[:], dtype=np.float64)
        longitude = np.asarray(longitude_array[:], dtype=np.float64)
        valid_time = np.asarray(valid_time_array[:], dtype=np.int64)
    except Exception as error:
        raise ValidationError(f"coordinate arrays are missing or unreadable: {error}") from error
    if not (latitude.size and longitude.size and valid_time.size):
        raise ValidationError("coordinate arrays must not be empty")
    if not (np.diff(latitude) > 0).all():
        raise ValidationError("latitude must be strictly increasing")
    if not (np.diff(longitude) > 0).all():
        raise ValidationError("longitude must be strictly increasing")
    convention = root.attrs.get("longitude_convention")
    if convention == "-180_180" and not ((longitude >= -180) & (longitude < 180)).all():
        raise ValidationError("longitude violates [-180, 180) convention")
    if convention == "0_360" and not ((longitude >= 0) & (longitude < 360)).all():
        raise ValidationError("longitude violates [0, 360) convention")
    if not (np.diff(valid_time) > 0).all():
        raise ValidationError("valid_time must be strictly increasing")

    arrays_checked = 0
    if plan is not None:
        expected_shape = (valid_time.size, latitude.size, longitude.size)
        for variable in plan.variables:
            try:
                group = cast(zarr.Group, root[variable.group])
                array = cast(zarr.Array[Any], group[variable.name])
            except Exception as error:
                raise ValidationError(f"missing array {variable.group}/{variable.name}") from error
            if array.shape != expected_shape:
                raise ValidationError(
                    f"wrong dimensions for {variable.name}: {array.shape} != {expected_shape}"
                )
            if array.attrs.get("_ARRAY_DIMENSIONS") != [
                "valid_time",
                "latitude",
                "longitude",
            ]:
                raise ValidationError(f"invalid dimension metadata for {variable.name}")
            for time in variable.valid_times:
                index = plan.valid_times.index(time)
                stored = np.asarray(array[index, :, :])
                physical = decode_values(stored, variable.encoding)
                if np.isnan(physical).all():
                    raise ValidationError(
                        f"{variable.name} is entirely missing at {time.isoformat()}"
                    )
                spec = SPECS_BY_NAME[variable.name]
                if spec.valid_range is not None:
                    finite = physical[np.isfinite(physical)]
                    lower, upper = spec.valid_range
                    tolerance = max(1, abs(lower), abs(upper)) * 0.05
                    if finite.size and (
                        float(finite.min()) < lower - tolerance
                        or float(finite.max()) > upper + tolerance
                    ):
                        raise ValidationError(
                            f"{variable.name} values fall outside the sanity range"
                        )
            arrays_checked += 1
    return {
        "zarr_format": 3,
        "coordinates": {
            "valid_time": int(valid_time.size),
            "latitude": int(latitude.size),
            "longitude": int(longitude.size),
        },
        "arrays_checked": arrays_checked,
    }


def validate_round_trip(
    path: Path,
    config: ProcessorConfig,
    plan: ProcessingPlan,
    report: InspectionReport,
    *,
    reader: GribReader | None = None,
) -> dict[str, Any]:
    """Sample direct fields and bboxes against a second sequential GRIB pass."""
    decoder = reader or EccodesReader()
    root = zarr.open_group(store=path, mode="r", zarr_format=3)
    latitude = np.asarray(plan.grid.latitude, dtype=np.float64)
    longitude = np.asarray(plan.grid.longitude, dtype=np.float64)
    direct = {item.name: item for item in plan.variables if item.group == "surface"}
    rng = random.Random(config.validation.random_seed)
    point_checks = 0
    bbox_checks = 0
    bytes_read = 0
    for source_file in report.source_files:
        for decoded in decoder.iter_file(report.input_dir / source_file.name):
            spec = match_variable(
                decoded.meta.short_name, decoded.meta.type_of_level, decoded.meta.level
            )
            if spec is None:
                continue
            if not accepts_step_type(spec, decoded.meta.step_type):
                continue
            variable = direct.get(spec.name)
            if variable is None:
                continue
            canonical = normalize_values(spec, decoded.values, decoded.meta.units)
            source_lat, source_lon, source_values = regular_grid(
                decoded.latitudes,
                decoded.longitudes,
                canonical,
                convention=config.longitude_convention,
            )
            lat_positions = np.searchsorted(latitude, source_lat)
            lon_positions = np.searchsorted(longitude, source_lon)
            valid_lat = np.flatnonzero(
                (lat_positions < latitude.size)
                & np.isclose(latitude[np.minimum(lat_positions, latitude.size - 1)], source_lat)
            )
            valid_lon = np.flatnonzero(
                (lon_positions < longitude.size)
                & np.isclose(longitude[np.minimum(lon_positions, longitude.size - 1)], source_lon)
            )
            if not valid_lat.size or not valid_lon.size:
                continue
            group = cast(zarr.Group, root[variable.group])
            array = cast(zarr.Array[Any], group[variable.name])
            time_index = plan.valid_times.index(decoded.meta.valid_time)
            sample_count = min(config.validation.point_samples, valid_lat.size * valid_lon.size)
            for _ in range(sample_count):
                source_y = int(valid_lat[rng.randrange(valid_lat.size)])
                source_x = int(valid_lon[rng.randrange(valid_lon.size)])
                target_y = int(lat_positions[source_y])
                target_x = int(lon_positions[source_x])
                stored = np.asarray([[array[time_index, target_y, target_x]]])
                actual = float(decode_values(stored, variable.encoding)[0, 0])
                expected = float(source_values[source_y, source_x])
                tolerance = variable.encoding.maximum_absolute_error + 2e-5
                if not np.isclose(actual, expected, atol=tolerance, rtol=0, equal_nan=True):
                    raise ValidationError(
                        f"round-trip error for {variable.name}: {actual} vs {expected}"
                    )
                point_checks += 1
                bytes_read += int(stored.nbytes)
            for _ in range(min(config.validation.bbox_samples, 1)):
                height = min(valid_lat.size, max(1, variable.layout.chunks[1] // 8))
                width = min(valid_lon.size, max(1, variable.layout.chunks[2] // 8))
                y0 = rng.randrange(max(1, valid_lat.size - height + 1))
                x0 = rng.randrange(max(1, valid_lon.size - width + 1))
                ys = valid_lat[y0 : y0 + height]
                xs = valid_lon[x0 : x0 + width]
                bbox_target_y = lat_positions[ys]
                bbox_target_x = lon_positions[xs]
                if np.all(np.diff(bbox_target_y) == 1) and np.all(np.diff(bbox_target_x) == 1):
                    block = np.asarray(
                        array[
                            time_index,
                            int(bbox_target_y[0]) : int(bbox_target_y[-1]) + 1,
                            int(bbox_target_x[0]) : int(bbox_target_x[-1]) + 1,
                        ]
                    )
                    physical = decode_values(block, variable.encoding)
                    expected_block = source_values[np.ix_(ys, xs)]
                    if not np.allclose(
                        physical,
                        expected_block,
                        atol=variable.encoding.maximum_absolute_error + 2e-5,
                        rtol=0,
                        equal_nan=True,
                    ):
                        raise ValidationError(f"bbox round-trip failed for {variable.name}")
                    bbox_checks += 1
                    bytes_read += int(block.nbytes)
    if point_checks == 0:
        raise ValidationError("round-trip validation found no comparable points")
    return {
        "point_checks": point_checks,
        "bbox_checks": bbox_checks,
        "bytes_read": bytes_read,
        "random_seed": config.validation.random_seed,
    }
