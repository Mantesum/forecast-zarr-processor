"""Point-forecast benchmark intended to run on the Django/API host over real NFS."""

from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast

import numpy as np
import zarr

DEFAULT_POINTS = (
    (55.7558, 37.6173),
    (1.3521, 103.8198),
    (-33.8688, 151.2093),
    (37.7749, -122.4194),
    (-33.9249, 18.4241),
)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _arrays(root: zarr.Group) -> list[tuple[str, zarr.Array[Any]]]:
    result: list[tuple[str, zarr.Array[Any]]] = []
    for group_name in ("surface", "height_80m", "height_100m", "atmosphere"):
        if group_name not in root:
            continue
        group = cast(zarr.Group, root[group_name])
        for name in group.array_keys():
            array = cast(zarr.Array[Any], group[name])
            if len(array.shape) == 3:
                result.append((f"{group_name}/{name}", array))
    return result


def _lower_cell(values: np.ndarray[Any, Any], requested: float) -> int:
    return max(0, min(int(np.searchsorted(values, requested, side="right")) - 1, len(values) - 2))


def _drop_linux_page_cache() -> None:
    if os.name != "posix":
        raise RuntimeError("cold-cache mode requires Linux and root access on the benchmark host")
    subprocess.run(("sync",), check=True)
    Path("/proc/sys/vm/drop_caches").write_text("3\n", encoding="ascii")


def benchmark_point_store(
    store: Path,
    *,
    points: tuple[tuple[float, float], ...] = DEFAULT_POINTS,
    iterations: int = 7,
    cold_cache: bool = False,
    api_url_template: str | None = None,
) -> dict[str, Any]:
    """Read every API field as a full-time 2x2 block at five or more locations."""
    if len(points) < 5:
        raise ValueError("at least five geographically different points are required")
    if iterations < 5:
        raise ValueError("at least five iterations are required for p95")
    root = zarr.open_group(store=store, mode="r", zarr_format=3)
    coordinates = cast(zarr.Group, root["coordinates"])
    latitude = np.asarray(cast(zarr.Array[Any], coordinates["latitude"])[:])
    longitude = np.asarray(cast(zarr.Array[Any], coordinates["longitude"])[:])
    arrays = _arrays(root)
    if not arrays:
        raise ValueError("store contains no forecast arrays")

    samples: list[float] = []
    point_results: list[dict[str, Any]] = []
    logical_bytes = 0
    estimated_objects: set[tuple[str, int, int, int]] = set()
    estimated_object_reads = 0
    estimated_uncompressed_bytes = 0
    for requested_lat, requested_lon in points:
        y = _lower_cell(latitude, requested_lat)
        x = _lower_cell(longitude, requested_lon)
        local: list[float] = []
        for _ in range(iterations):
            if cold_cache:
                _drop_linux_page_cache()
            started = time.perf_counter()
            sample_arrays = arrays
            if cold_cache:
                cold_root = zarr.open_group(store=store, mode="r", zarr_format=3)
                sample_arrays = _arrays(cold_root)
            for name, array in sample_arrays:
                block = np.asarray(array[:, y : y + 2, x : x + 2])
                logical_bytes += int(block.nbytes)
                tc, yc, xc = array.chunks
                selection_objects: set[tuple[str, int, int, int]] = set()
                for ti in range(0, array.shape[0], tc):
                    for yi in {y // yc, (y + 1) // yc}:
                        for xi in {x // xc, (x + 1) // xc}:
                            selection_objects.add((name, ti // tc, yi, xi))
                estimated_objects.update(selection_objects)
                estimated_object_reads += len(selection_objects)
                estimated_uncompressed_bytes += (
                    len(selection_objects) * tc * yc * xc * array.dtype.itemsize
                )
            elapsed = time.perf_counter() - started
            local.append(elapsed)
            samples.append(elapsed)
        point_results.append(
            {
                "requested": {"latitude": requested_lat, "longitude": requested_lon},
                "grid_cell": {"y": y, "x": x},
                "p50_seconds": statistics.median(local),
                "p95_seconds": _percentile(local, 0.95),
            }
        )

    api_result: dict[str, Any] | None = None
    if api_url_template:
        api_samples: list[float] = []
        for requested_lat, requested_lon in points:
            url = api_url_template.format(
                lat=urllib.parse.quote(str(requested_lat)),
                lon=urllib.parse.quote(str(requested_lon)),
            )
            # Populate Redis/application cache, then time cached responses.
            with urllib.request.urlopen(url, timeout=30) as response:
                response.read()
            for _ in range(iterations):
                started = time.perf_counter()
                with urllib.request.urlopen(url, timeout=30) as response:
                    response.read()
                api_samples.append(time.perf_counter() - started)
        api_result = {
            "mode": "cached_after_one_warmup_request",
            "p50_seconds": statistics.median(api_samples),
            "p95_seconds": _percentile(api_samples, 0.95),
            "samples": len(api_samples),
        }

    return {
        "schema_version": "1.0",
        "store": str(store.resolve()),
        "cache_mode": "cold_linux_page_cache" if cold_cache else "warm_or_uncontrolled_os_cache",
        "iterations_per_point": iterations,
        "points": point_results,
        "fields": [name for name, _ in arrays],
        "field_count": len(arrays),
        "valid_time_count": arrays[0][1].shape[0],
        "selection": "all valid_time, 2x2 latitude/longitude (linear interpolation input)",
        "zarr_nfs": {
            "p50_seconds": statistics.median(samples),
            "p95_seconds": _percentile(samples, 0.95),
            "samples": len(samples),
            "logical_result_bytes": logical_bytes,
            "estimated_unique_chunk_objects": len(estimated_objects),
            "estimated_chunk_object_reads": estimated_object_reads,
            "estimated_uncompressed_chunk_bytes": estimated_uncompressed_bytes,
            "note": (
                "object count is derived from chunk geometry; "
                "collect NFS client counters separately"
            ),
        },
        "api_cached": api_result,
    }


def benchmark_point_store_json(**kwargs: Any) -> str:
    return json.dumps(benchmark_point_store(**kwargs), indent=2, sort_keys=True)
