# Changelog

All notable changes follow Keep a Changelog conventions. The project uses semantic versioning.

## [Unreleased]

### Fixed

- Store derived 100 m wind power density as `float32` so extreme hurricane-force winds cannot
  overflow a statically planned `int16` range.

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
