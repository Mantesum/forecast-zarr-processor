# Changelog

All notable changes follow Keep a Changelog conventions. The project uses semantic versioning.

## [0.4.9] - 2026-08-12

### Changed

- Let the `plan` command reuse and refresh a valid cached plan, making orchestrator retries
  skip the expensive GRIB inspection as well as the conversion command.

## [0.4.8] - 2026-08-12

### Fixed

- Keep the source input identity stable when downloader rechecks only change volatile
  manifest timestamps or operation metadata, while still invalidating it for changed GRIB
  checksums, field contracts, forecast steps, or regions.
- Reuse a cached plan after such a recheck and refresh its raw manifest checksum before
  writing provenance.

## [0.4.7] - 2026-08-12

### Changed

- Validate deterministic samples from the beginning, middle, and end of each variable's
  forecast timeline instead of decoding every source file and every Zarr time slice.
- Keep full structural, shape, chunk-layout, metadata, and atomic publication checks while
  making the number of temporal validation samples configurable.

## [0.4.6] - 2026-08-12

### Changed

- Skip opening and decoding a source GRIB file when every inspected message is already
  present in the resumable ingestion checkpoint.

## [0.4.5] - 2026-08-12

### Changed

- Allow up to 16 rechunk workers on larger API hosts while retaining the conservative
  default of two workers.

## [0.4.4] - 2026-08-12

### Changed

- Cache the validated inspection report produced by `plan` and reuse it in `convert`
  when the configuration, manifest hash, and all source file sizes are unchanged. This
  removes a duplicate full GRIB inspection from orchestrated runs.

## [0.4.3] - 2026-08-12

### Changed

- Persist the resumable ingestion checkpoint and scan staging size once per source file
  instead of once per GRIB message, avoiding quadratic metadata and directory I/O.

## [0.4.2] - 2026-08-12

### Fixed

- Keep the runtime `forecast_zarr.__version__` metadata in sync with the package release.

## [0.4.1] - 2026-08-12

### Fixed

- Resume point-layout rechunking without deleting already completed variables.
- Rechunk independent variables concurrently according to `runtime.max_workers`.
- Avoid an increasingly expensive full staging-directory scan after every spatial chunk.

## [0.4.0] - 2026-08-12

### Added

- ProjectEOL point-access layout with full-time 32x32 chunks and safe two-phase rechunking.
- API-host benchmark for five 2x2 full-field point forecasts, p50/p95, cold cache, and cached API.

### Changed

- Structural validation now enforces the planned physical chunk shape before publication.

## [0.3.2] - 2026-08-01

### Fixed

- Ignore NOMADS side-effect messages such as 2 m specific humidity and surface temperature
  when schema 1.1 does not declare their exact field identities, keeping the output at exactly
  34 arrays.
- Continue to reject any declared schema 1.1 field that has no normalization mapping.

## [0.3.1] - 2026-08-01

### Fixed

- Matched the exact 34-field `forecast-ingest` 0.2.1 contract and its 21/5/3/5 Zarr group
  split.
- Renamed the canonical instantaneous PRATE array to `precipitation_flux` and require its
  native GRIB2 identity `0/1/7`; interval-average PRATE is ignored and `f000` is retained.
- Removed mappings for the no-longer-downloaded whole-atmosphere relative humidity, 2 m
  specific humidity, and surface temperature fields.
- Confirmed that fields split across files with the same forecast step, such as PWAT, merge
  onto one time coordinate.

## [0.3.0] - 2026-08-01

### Changed

- Removed all calculation and storage of derived wind speed, direction, humidity, density,
  shear, and wind-power-density arrays.
- Every normalized source field discovered in a GRIB run is now included automatically,
  regardless of an older local YAML selection list.
- Inspection now rejects an unmapped GRIB identity instead of publishing an incomplete Zarr.

### Added

- Direct mappings for GFS 2 m specific humidity, surface temperature, and instantaneous
  precipitation rate (`PRATE`). The older whole-atmosphere relative-humidity field remains
  readable for backward compatibility but is no longer selected by current profiles.

## [0.2.0] - 2026-07-31

### Added

- Exact field validation for `forecast-ingest` manifest schema 1.1, including native GRIB2
  parameter codes.
- General-weather, wind-energy, solar-energy, and combined processing configurations.
- Direct GFS fields at 80 and 100 metres, atmospheric boundary-layer fields, component cloud
  cover, longwave/shortwave radiation, albedo, precipitable water, and snow variables.
- Derived wind speed and direction at 10/80/100 m, 80 m relative humidity and density,
  10-to-100 m shear exponent, and 100 m wind power density.
- `surface`, `height_80m`, `height_100m`, `atmosphere`, and `derived` Zarr groups.
- `forecast-zarr profiles` command and updated deployment/retention documentation.

### Fixed

- Treat optional all-missing fields, such as snow over ocean, as fill values while continuing
  to enforce configured required variables.
- Aggregate repeated warnings for unselected GRIB messages.

## [0.1.0] - 2026-07-31

- Streaming ecCodes inspection and conversion for forecast-ingest schema 1.x.
- Normalized GFS, IFS, and AIFS surface variables on regular latitude/longitude grids.
- Zarr v3 sharding, Zstd compression, lossless and API-compact encodings.
- Budget-first planning, resumable staging, sampled round-trip validation, atomic publication.
- Typer CLI, benchmark, status command, systemd examples, and operator documentation.
