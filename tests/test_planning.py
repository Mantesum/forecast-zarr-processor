from __future__ import annotations

from pathlib import Path

from forecast_zarr.config import ChunkingConfig, StorageConfig
from forecast_zarr.inspection import inspect_run
from forecast_zarr.layout import choose_layout
from forecast_zarr.planning import create_plan
from tests.helpers import processor_config, source_run


def test_layout_targets_bounded_shards() -> None:
    layout = choose_layout((41, 721, 1440), 2, ChunkingConfig())
    assert 4 * 1024 * 1024 <= layout.uncompressed_shard_bytes <= 16 * 1024 * 1024
    assert all(shard >= chunk for shard, chunk in zip(layout.shards, layout.chunks, strict=True))


def test_plan_is_deterministic_and_includes_every_source_field(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    config = processor_config(tmp_path, run_dir).model_copy(
        update={
            "variables": ("air_temperature_2m",),
            "required_variables": ("air_temperature_2m",),
        }
    )
    report = inspect_run(config, reader=reader)
    first = create_plan(config, report)
    second = create_plan(config, report)
    assert first.dataset_id == second.dataset_id
    assert first.budget.passes
    assert {item.name for item in first.variables} == {
        "air_temperature_2m",
        "eastward_wind_10m",
        "northward_wind_10m",
        "precipitation_rate",
    }
    assert all(item.group != "derived" for item in first.variables)


def test_tiny_output_budget_fails_plan(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    config = processor_config(tmp_path, run_dir).model_copy(
        update={
            "storage": StorageConfig(
                total_budget_gib=1,
                min_free_gib=0,
                max_zarr_output_gib=0.000001,
                max_temporary_gib=0.5,
            )
        }
    )
    report = inspect_run(config, reader=reader)
    assert not create_plan(config, report).budget.passes
