from __future__ import annotations

from pathlib import Path

from forecast_zarr.config import load_config
from forecast_zarr.status import status_report


def test_config_paths_are_relative_to_yaml(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "test.yaml"
    path.write_text("input_run: ../raw\noutput_root: ../zarr\n", encoding="utf-8")
    config = load_config(path)
    assert config.input_run == (tmp_path / "raw").resolve()
    assert config.output_root == (tmp_path / "zarr").resolve()


def test_distributed_processor_configs_load() -> None:
    config_dir = Path(__file__).parents[1] / "configs"
    for name in ("gfs-projecteol.yaml", "aifs-global-light.yaml", "renewable-energy.yaml"):
        config = load_config(config_dir / name)
        assert config.longitude_convention == "-180_180"


def test_empty_status_is_healthy(tmp_path: Path) -> None:
    result = status_report(tmp_path / "zarr")
    assert result["status"] == "healthy"
    assert result["ready_count"] == 0
