# Data model

## Input contract

The input is one complete `forecast-ingest` run. Manifest schema 1.0 remains supported;
schema 1.1 is preferred because its `expected_fields` entries describe the exact parameter,
level, height, forecast interval, step type, and native GRIB2 code where needed.

The processor checks the manifest, safe file names, byte sizes, SHA-256 checksums, forecast
steps, license, attribution, and requested field identities against the real GRIB messages.
This prevents a similarly named field at the wrong height or with the wrong time statistic
from silently entering the Zarr dataset.

## Coordinates and groups

- `coordinates/valid_time`: UTC epoch seconds for all available forecast moments.
- `coordinates/latitude`: strictly increasing degrees north.
- `coordinates/longitude`: strictly increasing degrees east in the declared convention.
- `forecast_reference_time`: stored in root and variable attributes.

Data arrays use `(valid_time, latitude, longitude)`. They are grouped by physical level:

- `surface/`: surface and near-surface weather fields;
- `height_80m/`: wind, temperature, humidity, and pressure at 80 m above ground;
- `height_100m/`: wind and temperature at 100 m above ground;
- `atmosphere/`: whole-column and boundary-layer fields;

Only regular latitude/longitude grids are supported. Missing source steps are fill values and
are never interpolated. An optional field may be entirely missing for a time and area — for
example snow over ocean — while a configured required field must contain usable data.

## Source variables only

Direct variables retain their source parameter, level, units, interval statistic, license,
and attribution. Interval-average radiation and albedo are marked `time: mean`; accumulated
precipitation is marked `time: sum`; source `PRATE` is retained as instantaneous
`precipitation_flux` with units `kg m-2 s-1`. Only instantaneous PRATE is retained; an
interval-average PRATE message is ignored. Source fields split across multiple GRIB files at
the same forecast step, including the dedicated PWAT file, share one `valid_time` slice.

The processor never calculates additional meteorological or energy variables. Wind speed,
direction, air density, shear, wind power density, solar geometry, and generation estimates
belong in downstream API or site-specific modelling layers. Every GRIB identity must have an
explicit normalization mapping; otherwise inspection fails instead of silently dropping it.

For solar modelling, shortwave radiation is retained as a horizontal-surface forecast input.
DNI, DHI, plane-of-array irradiance, cell temperature, and electrical power are intentionally
left to a site-specific downstream model that knows location and PV installation geometry.

## Encoding and provenance

Names and metadata follow CF conventions where an applicable standard name exists.
`api_compact` arrays record scale, offset, fill value, and maximum absolute packing error;
unsafe ranges fall back to float32. `lossless` always stores decoded float32 values.

`provenance/source-manifest.json` is the exact ingest handoff. The processing manifest schema
1.1 records input hashes, files, variables, valid times, software versions, layouts, encoding,
measured size, validation results, and the complete processing plan. `READY.json` is written
last and is the publication marker.
