# Ubuntu deployment

These are operator instructions only; the project does not change a host automatically.

## Prerequisites

Install Python 3.12+ and `uv`. The locked Python environment installs the official ECMWF `eccodeslib` binary package (ecCodes 2.42+) on Linux. A separately managed system ecCodes installation is optional; if your organization requires one, confirm that it is version 2.42 or newer and configure the ecCodes library search explicitly.

```bash
uv --version
```

Clone the repository into `/opt/forecast-zarr-processor`, create `/srv/forecast-data`, and install locked dependencies:

```bash
cd /opt/forecast-zarr-processor
uv sync --frozen
uv run python -m eccodes selfcheck
install -d -m 0750 /srv/forecast-data/zarr /srv/forecast-data/logs
```

Copy and edit a configuration under `/etc/forecast-zarr/`. The input must point at a complete forecast-ingest run. Test `inspect`, `plan`, and one foreground `convert` before enabling scheduling.

## systemd

Copy the unit files from `systemd/`, create `/etc/forecast-zarr/forecast-zarr.env`, and adjust `User`, paths, and the configuration selection for your host. Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now forecast-zarr.timer
systemctl status forecast-zarr.timer
journalctl -u forecast-zarr.service
```

The example service is hardened, runs at most one conversion, and treats JSON stderr as journal data. A production scheduler must update the selected `input_run` after forecast-ingest publishes a new manifest. The timer alone does not discover a "latest" directory.
