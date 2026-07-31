# forecast-zarr-processor

`forecast-zarr-processor` is a standalone, budget-aware Python 3.12 application that turns a complete [forecast-ingest](https://github.com/Mantesum/forecast-ingest) run into an immutable physical Zarr v3 store. It is the processing layer for a future ProjectEOL weather API; it does not download forecasts and does not provide an HTTP API, map server, database, or browser UI.

## Architecture

```text
forecast-ingest output
  manifest.json + validated GRIB2 files
                  |
                  v
discover -> inspect -> plan -> convert -> validate -> publish
             ecCodes       staging Zarr v3        atomic rename
                                                   + READY.json
```

The processor checks the real forecast-ingest schema 1.x contract, every file size and SHA-256, expected GRIB parameters and steps, and regular latitude/longitude geometry. It scans GRIB messages sequentially, writes one spatial field at a time, uses Zstd-compressed Zarr v3 sharding, and never materializes the complete forecast in RAM. The default limits target a 6-core, 12 GiB RAM, 50 GiB SSD Ubuntu host: two workers, an 8 GiB memory budget, a 40 GiB managed storage budget, and 10 GiB minimum free space.

One forecast run becomes one store:

```text
data/zarr/{provider}/{model}/{run_utc}/{dataset_id}.zarr/
  zarr.json
  coordinates/
  surface/
  derived/
  provenance/
    source-manifest.json
    processing-manifest.json
  READY.json
```

Primary fields use `(valid_time, latitude, longitude)`. Latitude is strictly increasing; longitude uses one recorded convention (default `[-180, 180)`). Direct u/v wind components are always retained when selected. Wind speed is the only calculated meteorological field in this release.

## Quick start

The Python environment includes the ECMWF ecCodes binary library on supported platforms. Install the project with:

```bash
uv sync --group dev
uv run forecast-zarr inspect /srv/forecast-data/raw/noaa-gfs/gfs/20250101T000000Z/REQUEST_HASH
uv run forecast-zarr plan --config configs/gfs-projecteol.yaml
uv run forecast-zarr convert --config configs/gfs-projecteol.yaml
uv run forecast-zarr validate /srv/forecast-data/zarr/noaa-gfs/gfs/20250101T000000Z/DATASET_ID.zarr
uv run forecast-zarr status --root /srv/forecast-data/zarr
```

Update `input_run` in the example configuration to the directory containing `manifest.json`. Relative paths are resolved against the configuration file, not the current shell directory.

For AIFS Single v2:

```bash
uv run forecast-zarr plan --config configs/aifs-global-light.yaml
uv run forecast-zarr convert --config configs/aifs-global-light.yaml
```

Compare three layouts on a small run:

```bash
uv run forecast-zarr benchmark --config configs/benchmark.yaml
```

The benchmark reports conversion time, store size, file count, point-read time, bbox-read time, and bytes returned by the sampled reads.

## Encoding and reliability

`lossless` stores float32 values at the physical precision delivered by ecCodes. Default `api_compact` uses int16 only when the observed range fits the variable's documented maximum error (temperature and wind 0.01 in their canonical units, pressure 1 Pa). `scale_factor`, `add_offset`, `_FillValue`, and the error bound are recorded. Unsafe ranges fall back to float32 with the reason in metadata.

Conversion uses a dataset-specific staging directory and durable checkpoint. A retry resumes completed messages. Conflicting overlaps are rejected. The store is validated against sampled GRIB points and bboxes before `READY.json` is written and the directory is atomically moved into its final location. Repeating the same input and effective configuration returns the same dataset ID.

See [data model](docs/data-model.md), [operations](docs/operations.md), [Ubuntu deployment](docs/ubuntu-deployment.md), and [future map rendering](docs/future-map-rendering.md).

## Known limitations

Version 0.1 supports regular latitude/longitude grids only. Weather code is stored only when the provider supplies a directly usable code; it is not inferred. GFS `sdswrf` is supported as shortwave flux, while accumulated ECMWF `ssrd` is deliberately left unmapped until interval de-accumulation is implemented and tested. Multiple disjoint input boxes share one coordinate envelope, with uncovered cells represented by fill values.

## Development

```bash
uv sync --group dev
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest
```

Only tiny synthetic arrays and mocked GRIB readers belong in tests. Never commit forecast GRIB or Zarr datasets.

## License

The software is licensed under Apache-2.0. Forecast data retain the provider license and attribution copied from the input manifest into every output store.
