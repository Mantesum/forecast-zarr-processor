# Changelog

All notable changes follow Keep a Changelog conventions. The project uses semantic versioning.

## [Unreleased]

### Added

- Streaming ecCodes inspection and conversion for forecast-ingest schema 1.x.
- Normalized GFS, IFS, and AIFS surface variables on regular latitude/longitude grids.
- Zarr v3 sharding, Zstd compression, lossless and API-compact encodings.
- Budget-first planning, resumable staging, sampled round-trip validation, atomic publication.
- Typer CLI, benchmark, status command, systemd examples, and operator documentation.

### Fixed

- Quote longitude conventions in distributed YAML configurations so they load as strings.
- Select instantaneous GFS total-cloud-cover fields instead of conflicting interval averages.
- Select the shortest GFS precipitation accumulation ending at each valid time instead of
  mixing it with the run-total accumulation.

## [0.1.0] - 2026-07-31

- Initial publication-ready implementation.
