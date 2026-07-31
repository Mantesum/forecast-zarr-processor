"""Streaming GRIB-to-Zarr conversion and resumable checkpoints."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import numpy.typing as npt

from forecast_zarr.config import ProcessorConfig
from forecast_zarr.errors import BudgetExceededError, InputContractError
from forecast_zarr.grib import EccodesReader, GribReader
from forecast_zarr.inspection import match_message, selected_message_keys
from forecast_zarr.io import directory_size, read_json, write_json_atomic
from forecast_zarr.models import InspectionReport, ProcessingPlan
from forecast_zarr.normalization import (
    DERIVED_DEPENDENCIES,
    decode_values,
    encode_values,
    normalize_values,
    regular_grid,
)
from forecast_zarr.store import ForecastStore

GIB = 1024**3


def _checkpoint_path(path: Path) -> Path:
    return path / "provenance" / "checkpoint.json"


def _load_checkpoint(path: Path, dataset_id: str) -> set[str]:
    checkpoint = _checkpoint_path(path)
    if not checkpoint.exists():
        return set()
    raw = read_json(checkpoint)
    if not isinstance(raw, dict) or raw.get("dataset_id") != dataset_id:
        raise InputContractError("invalid or foreign staging checkpoint")
    processed = raw.get("processed", [])
    if not isinstance(processed, list):
        raise InputContractError("invalid staging checkpoint entries")
    return {str(item) for item in processed}


def _save_checkpoint(path: Path, dataset_id: str, processed: set[str]) -> None:
    write_json_atomic(
        _checkpoint_path(path),
        {"schema_version": "1.0", "dataset_id": dataset_id, "processed": sorted(processed)},
    )


def _guard_disk(config: ProcessorConfig, plan: ProcessingPlan) -> None:
    size = directory_size(plan.staging_path)
    if size > config.storage.max_zarr_output_gib * GIB:
        raise BudgetExceededError("staging store exceeded max_zarr_output_gib")
    free = shutil.disk_usage(plan.staging_path).free
    if free < config.storage.min_free_gib * GIB:
        raise BudgetExceededError("free space fell below min_free_gib during conversion")


def convert_messages(
    config: ProcessorConfig,
    plan: ProcessingPlan,
    report: InspectionReport,
    *,
    reader: GribReader | None = None,
) -> ForecastStore:
    """Write direct fields sequentially, then derived wind one time plane at a time."""
    decoder = reader or EccodesReader()
    if plan.staging_path.exists():
        if not config.resume:
            raise InputContractError(
                f"staging directory already exists and resume is disabled: {plan.staging_path}"
            )
        store = ForecastStore.open(plan.staging_path, plan)
        processed = _load_checkpoint(plan.staging_path, plan.dataset_id)
    else:
        store = ForecastStore.create(plan.staging_path, plan, report, config)
        processed = set()
        _save_checkpoint(plan.staging_path, plan.dataset_id, processed)
    plans = {item.name: item for item in plan.variables if item.group != "derived"}
    selected = selected_message_keys(report.messages)
    message_counter = 0
    for source_file in report.source_files:
        for decoded in decoder.iter_file(report.input_dir / source_file.name):
            key = f"message:{source_file.name}:{decoded.meta.message_index}"
            if key in processed:
                continue
            if decoded.meta.source_key not in selected:
                processed.add(key)
                _save_checkpoint(plan.staging_path, plan.dataset_id, processed)
                continue
            spec = match_message(decoded.meta)
            if spec is None:
                processed.add(key)
                _save_checkpoint(plan.staging_path, plan.dataset_id, processed)
                continue
            variable = plans.get(spec.name)
            if variable is not None:
                canonical = normalize_values(spec, decoded.values, decoded.meta.units)
                lat, lon, values = regular_grid(
                    decoded.latitudes,
                    decoded.longitudes,
                    canonical,
                    convention=config.longitude_convention,
                )
                store.write_block(variable, decoded.meta.valid_time, lat, lon, values)
            processed.add(key)
            _save_checkpoint(plan.staging_path, plan.dataset_id, processed)
            message_counter += 1
            if message_counter % 8 == 0:
                _guard_disk(config, plan)
    _write_derived(store, plan, processed)
    _save_checkpoint(plan.staging_path, plan.dataset_id, processed)
    _guard_disk(config, plan)
    return store


def _write_derived(store: ForecastStore, plan: ProcessingPlan, processed: set[str]) -> None:
    by_name = {item.name: item for item in plan.variables}
    for variable in plan.variables:
        dependencies = DERIVED_DEPENDENCIES.get(variable.name)
        if dependencies is None:
            continue
        output = store.array(variable)
        for index, valid_time in enumerate(plan.valid_times):
            key = f"derived:{variable.name}:{valid_time.isoformat()}"
            if key in processed:
                continue
            components = {
                name: decode_values(
                    np.asarray(store.array(by_name[name])[index, :, :]),
                    by_name[name].encoding,
                )
                for name in dependencies
            }
            values = _calculate_derived(variable.name, components)
            output[index, :, :] = encode_values(values, variable.encoding)
            processed.add(key)


def _calculate_derived(
    name: str,
    values: dict[str, npt.NDArray[np.float64]],
) -> npt.NDArray[np.float64]:
    if name.startswith("wind_speed_"):
        height = name.removeprefix("wind_speed_")
        return np.hypot(values[f"eastward_wind_{height}"], values[f"northward_wind_{height}"])
    if name.startswith("wind_from_direction_"):
        height = name.removeprefix("wind_from_direction_")
        u = values[f"eastward_wind_{height}"]
        v = values[f"northward_wind_{height}"]
        direction = (270 - np.degrees(np.arctan2(v, u))) % 360
        return np.where(np.hypot(u, v) > 1e-9, direction, np.nan)
    if name in {"relative_humidity_80m", "air_density_80m"}:
        temperature = values["air_temperature_80m"]
        specific_humidity = values["specific_humidity_80m"]
        pressure = values["air_pressure_80m"]
        if name == "air_density_80m":
            virtual_temperature = temperature * (1 + 0.61 * specific_humidity)
            return pressure / (287.05 * virtual_temperature)
        epsilon = 0.622
        vapor_pressure = (
            specific_humidity * pressure / (epsilon + (1 - epsilon) * specific_humidity)
        )
        celsius = temperature - 273.15
        saturation_pressure = 611.2 * np.exp(17.67 * celsius / (celsius + 243.5))
        return 100 * vapor_pressure / saturation_pressure
    if name == "wind_shear_exponent_10m_100m":
        speed_10m = np.hypot(values["eastward_wind_10m"], values["northward_wind_10m"])
        speed_100m = np.hypot(values["eastward_wind_100m"], values["northward_wind_100m"])
        valid = (speed_10m > 0.1) & (speed_100m > 0.1)
        result = np.full(speed_10m.shape, np.nan, dtype=np.float64)
        result[valid] = np.log(speed_100m[valid] / speed_10m[valid]) / np.log(10)
        return result
    if name == "wind_power_density_100m":
        speed = np.hypot(values["eastward_wind_100m"], values["northward_wind_100m"])
        virtual_temperature = values["air_temperature_80m"] * (
            1 + 0.61 * values["specific_humidity_80m"]
        )
        density = values["air_pressure_80m"] / (287.05 * virtual_temperature)
        return np.asarray(0.5 * density * speed**3, dtype=np.float64)
    raise InputContractError(f"unknown derived variable: {name}")
