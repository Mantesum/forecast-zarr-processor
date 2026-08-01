# forecast-zarr-processor

`forecast-zarr-processor` converts a complete
[`forecast-ingest`](https://github.com/Mantesum/forecast-ingest) GRIB2 run into an
immutable, validated Zarr v3 store. Version 0.3 supports four ready-made data bundles:
general weather, wind-power forecasting, solar-power forecasting, and their complete union.

The program does not download forecasts and does not expose an HTTP API. Its place in the
pipeline is:

```text
NOAA GFS -> forecast-ingest -> validated GRIB2 -> forecast-zarr-processor -> Zarr v3 -> API/ML
```

## What version 0.3 processes

The processor understands `forecast-ingest` manifest schema 1.1 and checks the exact GRIB
identity of every requested field: parameter, level, height, and time statistic. This is
important for fields whose short name alone is ambiguous, including the GFS boundary-layer
height parameter.

The processor writes every source parameter discovered in the GRIB run. The current GFS
`full_energy` download from `forecast-ingest` 0.2.1 produces exactly 34 source arrays:

- ordinary forecast fields: temperature, humidity, dew point, pressure, 10 m wind,
  precipitation, clouds, visibility, solar radiation, and terrain height;
- wind-energy fields: wind components and temperature at 80/100 m, humidity and pressure at
  80 m, gusts, boundary-layer height, friction velocity, and roughness length;
- solar-energy fields: downwelling and upwelling shortwave radiation, downwelling longwave
  radiation, low/middle/high cloud cover, albedo, precipitable water, snow depth, and snow
  water equivalent;
- instantaneous surface precipitation rate (`PRATE`) alongside accumulated precipitation.

`PRATE` is written as `surface/precipitation_flux`; only its instantaneous GRIB message is
used, including at `f000`. An interval-average PRATE message returned by NOMADS is ignored.
Precipitable water may arrive in a separate GRIB file with the same forecast step and valid
time as the main file; the processor merges both files onto the shared time coordinate.

The result is split into `surface/`, `height_80m/`, `height_100m/`, and `atmosphere/`
groups. Every field has dimensions `(valid_time, latitude, longitude)`. The processor does
not calculate wind speed, direction, density, shear, power density, or any other new field.
An unmapped GRIB identity is a hard input-contract error, so a successful conversion cannot
silently omit a source parameter.

For solar power, GFS shortwave radiation is a horizontal-surface irradiance input comparable
to GHI. The processor deliberately does not invent DNI, DHI, plane-of-array irradiance, or PV
power: those calculations require solar geometry, site coordinates, panel tilt/azimuth,
tracking type, and equipment characteristics. They belong in a later site-specific model.

## Quick start on Ubuntu

Install the project and verify ecCodes:

```bash
git clone https://github.com/Mantesum/forecast-zarr-processor.git
cd forecast-zarr-processor
uv sync --frozen
uv run python -m eccodes selfcheck
```

See the available bundles:

```bash
uv run forecast-zarr profiles
```

Choose the configuration matching the `forecast-ingest` download:

| Purpose | Ingest profile | Zarr configuration |
|---|---|---|
| General weather | `weather` | `configs/gfs-global-weather-10day.yaml` |
| Wind generation | `wind_energy` | `configs/gfs-global-wind-energy-10day.yaml` |
| Solar generation | `solar_energy` | `configs/gfs-global-solar-energy-10day.yaml` |
| All fields in one run | `full_energy` | `configs/gfs-global-full-energy-10day.yaml` |

Edit only `input_run` first. It must point to the exact directory containing the completed
ingest `manifest.json`, for example:

```yaml
input_run: /srv/forecast-data/raw/noaa-gfs/gfs/20260731T000000Z/REQUEST_HASH
output_root: /srv/forecast-data/zarr
```

Then inspect, plan, convert, and validate:

```bash
uv run forecast-zarr inspect /srv/forecast-data/raw/noaa-gfs/gfs/20260731T000000Z/REQUEST_HASH
uv run forecast-zarr plan --config configs/gfs-global-full-energy-10day.yaml
uv run forecast-zarr convert --config configs/gfs-global-full-energy-10day.yaml
uv run forecast-zarr validate /srv/forecast-data/zarr/noaa-gfs/gfs/20260731T000000Z/DATASET_ID.zarr
uv run forecast-zarr status --root /srv/forecast-data/zarr
```

Relative paths in YAML are resolved from the configuration file's directory. `plan` performs
all safety and storage estimates but does not create a Zarr store.

## Reliability and resource limits

The processor verifies the source manifest, sizes, SHA-256 checksums, forecast steps, exact
GRIB fields, and grid geometry before conversion. It reads GRIB messages sequentially and
writes one spatial field at a time instead of loading the whole forecast into memory.

Conversion takes place in a dataset-specific `.staging` directory and is resumable. Before
publication, the program validates structure and sampled values against GRIB. Only then does
it write `READY.json` and atomically expose the final store. Repeating the same input and
effective configuration produces the same dataset ID.

Default limits target a modest Ubuntu VM: two workers, 8 GiB memory, 40 GiB managed storage,
26 GiB maximum output, 6 GiB temporary data, and at least 10 GiB remaining disk space. Review
these values for a global ten-day `full_energy` run before regular scheduling.

`api_compact` encoding uses integer packing only when the observed range meets the documented
error bound; otherwise it safely falls back to float32. Missing optional fields such as snow
over an all-ocean subset remain fill values and do not invalidate the dataset.

## Operations

Process only an ingest run whose manifest status is `complete`. Keep source GRIB until the
Zarr store has `READY.json`, passes `forecast-zarr validate`, and any required backup is done.
Deletion of old GRIB remains an explicit external retention step so a conversion failure can
never remove the only source copy.

See the [data model](docs/data-model.md), [operations guide](docs/operations.md),
[Ubuntu deployment](docs/ubuntu-deployment.md), and
[future map rendering notes](docs/future-map-rendering.md).

## Development

```bash
uv sync --group dev
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest
```

Never commit forecast GRIB or generated Zarr datasets.

## License

The software is licensed under Apache-2.0. Forecast data retain the provider license and
attribution copied from the input manifest into every output store.
