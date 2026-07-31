# Data model

The input is the public `forecast-ingest` schema 1.x handoff: a `complete` manifest, `validated` file entries, safe file names, byte sizes, `sha256:` checksums, forecast steps, regions, license, attribution, and an `applied_plan`. The processor additionally checks each GRIB file through ecCodes against the embedded expected short names and step.

The output is physical Zarr v3, not a Kerchunk or VirtualiZarr reference. Virtual datasets can be useful for an archive tier, but physical arrays make latency, compression, and read amplification predictable for a public API.

## Coordinates

- `coordinates/valid_time`: UTC epoch seconds for all actually available forecast moments.
- `coordinates/latitude`: strictly increasing degrees north.
- `coordinates/longitude`: strictly increasing degrees east in the root's declared convention.
- `forecast_reference_time`: recorded in root and variable attributes.

Surface and derived arrays have dimensions `(valid_time, latitude, longitude)`. Missing source steps remain `_FillValue`; they are not silently interpolated. Only `regular_ll` is supported in version 0.1. A native unstructured grid fails with `unsupported_grid_type` before any final store appears.

## Variables and provenance

Names and common metadata follow CF conventions. Each array records canonical units, `standard_name` where one exists, a readable name, source GRIB short names and levels, conversion software/version, license, and attribution. Compact arrays also record their scale, offset, fill value, and maximum absolute error.

`provenance/source-manifest.json` is an exact JSON copy of the handoff. `processing-manifest.json` records input hashes, source files, variables, valid times, software versions, layout, encoding, measured size, validation counts, timing, and status. `READY.json` is the compact publication marker and is written last.

Accumulated ECMWF `ssrd` is not labelled as instantaneous shortwave flux. It remains unmapped in version 0.1 until tested de-accumulation across forecast intervals is available. GFS `sdswrf`, whose decoded units are flux, maps directly to `surface_downwelling_shortwave_flux_in_air`.
