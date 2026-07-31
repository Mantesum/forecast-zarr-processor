# Ubuntu deployment

These instructions do not modify the host automatically.

## Install

Install Python 3.12+ and `uv`, then clone and prepare the locked environment:

```bash
git clone https://github.com/Mantesum/forecast-zarr-processor.git
cd forecast-zarr-processor
uv sync --frozen
uv run python -m eccodes selfcheck
sudo install -d -o "$USER" -g "$USER" -m 0750 /srv/forecast-data/zarr /srv/forecast-data/logs
```

The Linux environment installs the ECMWF `eccodeslib` binary package. A separately managed
system ecCodes installation is optional.

## Configure one run

Copy the configuration corresponding to the ingest profile. If you download the combined
bundle, use:

```bash
cp configs/gfs-global-full-energy-10day.yaml configs/gfs-local-full-energy.yaml
```

Edit `input_run` in the local copy so it points at the directory containing `manifest.json`:

```yaml
input_run: /home/mantesum/forecast-ingest/data/raw/noaa-gfs/gfs/20260731T000000Z/REQUEST_HASH
output_root: /srv/forecast-data/zarr
```

Verify the handoff before conversion:

```bash
uv run forecast-zarr inspect /home/mantesum/forecast-ingest/data/raw/noaa-gfs/gfs/20260731T000000Z/REQUEST_HASH
uv run forecast-zarr plan --config configs/gfs-local-full-energy.yaml
uv run forecast-zarr convert --config configs/gfs-local-full-energy.yaml
uv run forecast-zarr status --root /srv/forecast-data/zarr
```

The final `convert` output prints the published store path. Validate that exact path with
`forecast-zarr validate`.

## systemd

The files in `systemd/` are examples. Copy the service, timer, chosen YAML, and optional
environment file into `/etc`, then adjust `User`, paths, resource limits, and configuration:

```bash
sudo cp systemd/forecast-zarr.service systemd/forecast-zarr.timer /etc/systemd/system/
sudo install -d -m 0755 /etc/forecast-zarr
sudo cp configs/gfs-global-full-energy-10day.yaml /etc/forecast-zarr/
sudo systemctl daemon-reload
sudo systemctl enable --now forecast-zarr.timer
systemctl status forecast-zarr.timer
journalctl -u forecast-zarr.service
```

The example service is hardened and permits one conversion at a time. Its timer does not
discover new ingest runs or rewrite `input_run`; production orchestration must select each
new immutable run after ingest finishes. This can later be replaced by a small handoff script
that receives the manifest path, runs plan/convert/validate, and only then triggers retention.
