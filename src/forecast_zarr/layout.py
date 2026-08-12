"""Grid- and dtype-aware chunk/shard selection."""

from __future__ import annotations

import math

from forecast_zarr.config import ChunkingConfig
from forecast_zarr.models import ArrayLayout


def choose_layout(
    shape: tuple[int, int, int], itemsize: int, config: ChunkingConfig
) -> ArrayLayout:
    """Choose either the legacy map layout or one object per point-friendly tile."""
    times, latitudes, longitudes = shape
    if config.access_pattern == "point":
        spatial = config.point_spatial_chunk
        chunks = (times, min(latitudes, spatial), min(longitudes, spatial))
        return ArrayLayout(
            chunks=chunks,
            shards=chunks,
            uncompressed_shard_bytes=math.prod(chunks) * itemsize,
        )
    time_chunk = min(times, config.time_chunk)
    time_shard = min(times, max(time_chunk, config.time_shard))
    target_bytes = int(config.target_shard_mib * 1024 * 1024)
    target_cells = max(1, target_bytes // max(1, itemsize * time_shard))
    aspect = longitudes / max(1, latitudes)
    lat_shard = int(math.sqrt(target_cells / max(aspect, 1e-9)))
    lat_shard = min(latitudes, config.max_spatial_shard, max(config.min_spatial_chunk, lat_shard))
    lon_shard = min(
        longitudes,
        config.max_spatial_shard,
        max(config.min_spatial_chunk, target_cells // max(1, lat_shard)),
    )
    lat_chunk = min(lat_shard, config.max_spatial_chunk)
    lon_chunk = min(lon_shard, config.max_spatial_chunk)
    lat_shard = max(lat_chunk, math.ceil(lat_shard / lat_chunk) * lat_chunk)
    lon_shard = max(lon_chunk, math.ceil(lon_shard / lon_chunk) * lon_chunk)
    lat_shard = min(latitudes, lat_shard)
    lon_shard = min(longitudes, lon_shard)
    return ArrayLayout(
        chunks=(time_chunk, lat_chunk, lon_chunk),
        shards=(time_shard, lat_shard, lon_shard),
        uncompressed_shard_bytes=time_shard * lat_shard * lon_shard * itemsize,
    )
