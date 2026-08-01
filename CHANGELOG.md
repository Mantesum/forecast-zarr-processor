# Changelog

All notable changes follow Keep a Changelog conventions. The project uses semantic versioning.

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
