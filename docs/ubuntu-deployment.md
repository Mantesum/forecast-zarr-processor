# Ubuntu deployment

These are operator instructions only; the project does not install system packages or change a host automatically.

## Prerequisites

Install Python 3.12+, `uv`, and ecCodes 2.42+ using your organization's approved package source. On supported Ubuntu releases the required packages are typically `libeccodes0`, `libeccodes-dev`, and `libeccodes-tools`; confirm the available version before deployment.

```bash
codes_info -v
uv --version
```

Clone the repository into `/opt/forecast-zarr-processor`, create `/srv/forecast-data`, and install locked dependencies:

```bash
cd /opt/forecast-zarr-processor
uv sync --frozen
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

