"""Reproducible comparison of at least three chunk/shard strategies."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

import numpy as np
import yaml
import zarr
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from forecast_zarr.config import ChunkingConfig, ProcessorConfig
from forecast_zarr.errors import ConfigurationError
from forecast_zarr.grib import GribReader
from forecast_zarr.io import directory_size
from forecast_zarr.pipeline import run_convert


class BenchmarkStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    chunking: ChunkingConfig


class BenchmarkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    processor: ProcessorConfig
    strategies: tuple[BenchmarkStrategy, ...] = Field(min_length=3)


def load_benchmark_config(path: Path) -> BenchmarkConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        config = BenchmarkConfig.model_validate(raw)
    except (OSError, yaml.YAMLError, PydanticValidationError) as error:
        raise ConfigurationError(f"invalid benchmark configuration: {error}") from error
    base = path.resolve().parent
    processor = config.processor
    input_run = (
        processor.input_run
        if processor.input_run.is_absolute()
        else (base / processor.input_run).resolve()
    )
    output_root = (
        processor.output_root
        if processor.output_root.is_absolute()
        else (base / processor.output_root).resolve()
    )
    return config.model_copy(
        update={
            "processor": processor.model_copy(
                update={"input_run": input_run, "output_root": output_root}
            )
        }
    )


def _read_metrics(path: Path) -> dict[str, Any]:
    root = zarr.open_group(store=path, mode="r", zarr_format=3)
    surface = cast(zarr.Group, root["surface"])
    group_name = "surface" if list(surface.array_keys()) else "derived"
    group = cast(zarr.Group, root[group_name])
    array_name = next(iter(group.array_keys()))
    array = cast(zarr.Array[Any], group[array_name])
    time_index = array.shape[0] // 2
    y = array.shape[1] // 2
    x = array.shape[2] // 2
    started = time.perf_counter()
    point = np.asarray(array[:, y, x])
    point_seconds = time.perf_counter() - started
    height = min(180, array.shape[1])
    width = min(360, array.shape[2])
    y0 = max(0, y - height // 2)
    x0 = max(0, x - width // 2)
    started = time.perf_counter()
    bbox = np.asarray(array[time_index, y0 : y0 + height, x0 : x0 + width])
    bbox_seconds = time.perf_counter() - started
    return {
        "sample_array": f"{group_name}/{array_name}",
        "point_read_seconds": point_seconds,
        "bbox_read_seconds": bbox_seconds,
        "bytes_read": int(point.nbytes + bbox.nbytes),
    }


def run_benchmark(config: BenchmarkConfig, *, reader: GribReader | None = None) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for strategy in config.strategies:
        processor = config.processor.model_copy(update={"chunking": strategy.chunking})
        started = time.perf_counter()
        output = run_convert(processor, reader=reader)
        conversion_seconds = time.perf_counter() - started
        metrics = _read_metrics(output)
        results.append(
            {
                "strategy": strategy.name,
                "output": str(output),
                "conversion_seconds": conversion_seconds,
                "size_bytes": directory_size(output),
                "file_count": sum(1 for item in output.rglob("*") if item.is_file()),
                **metrics,
            }
        )
    return {"schema_version": "1.0", "strategies": results}


def benchmark_json(config: BenchmarkConfig, *, reader: GribReader | None = None) -> str:
    return json.dumps(run_benchmark(config, reader=reader), indent=2, sort_keys=True)
