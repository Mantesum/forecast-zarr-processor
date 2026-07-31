# Future interactive map rendering

Recommended architecture:

```text
Zarr v3 -> tile generation service -> cache/CDN -> browser WebGL
```

Zarr remains the authoritative analysis and API source, not the CDN delivery format. A tile service should read bounded Zarr regions and produce reusable artifacts once per run/time/layer/style.

Temperature, cloud cover, and precipitation are suited to colorized raster tiles (PNG, WebP, or AVIF). The stored eastward and northward wind components should feed binary or texture tiles for GPU particle animation; wind speed alone is insufficient because it loses direction. A browser shader can sample two-channel u/v textures and advect particles without server work per animation frame.

Use a cache key such as:

```text
provider/model/run/valid_time/layer/z/x/y/style_version
```

The browser should not read Zarr directly: it would need metadata traversal, shard/chunk range planning, decompression, compact decoding, access control, and provider-specific failure handling. Those concerns belong in the server layer. Rendering must not be repeated for every user; deterministic tiles should be shared through Nginx or Cloudflare cache and later persisted in MinIO/S3-compatible object storage.

Point forecasts and map tiles are separate products. A point API reads a tiny spatial selection across many times and returns meteorological values. A tile request reads a rectangular spatial region at one time and returns visualization-ready pixels or vectors. They benefit from the same sharded Zarr source but require different response formats and cache policies.

