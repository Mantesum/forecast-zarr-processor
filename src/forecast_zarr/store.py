"""Physical Zarr v3 layout and block-aligned writes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
import numpy.typing as npt
import zarr
from zarr.codecs import ZstdCodec

from forecast_zarr import __version__
from forecast_zarr.config import ProcessorConfig
from forecast_zarr.errors import InputContractError
from forecast_zarr.models import InspectionReport, ProcessingPlan, VariablePlan
from forecast_zarr.normalization import encode_values


def _epoch_seconds(value: datetime) -> int:
    return int(value.timestamp())


class ForecastStore:
    """Small wrapper around one immutable-in-the-final-location Zarr v3 store."""

    def __init__(self, root: zarr.Group, plan: ProcessingPlan) -> None:
        self.root = root
        self.plan = plan
        self.time_index = {value: index for index, value in enumerate(plan.valid_times)}
        self.latitude = np.asarray(plan.grid.latitude, dtype=np.float64)
        self.longitude = np.asarray(plan.grid.longitude, dtype=np.float64)

    @classmethod
    def create(
        cls,
        path: Path,
        plan: ProcessingPlan,
        report: InspectionReport,
        config: ProcessorConfig,
    ) -> ForecastStore:
        path.parent.mkdir(parents=True, exist_ok=True)
        root = zarr.open_group(store=path, mode="w", zarr_format=3)
        root.attrs.update(
            {
                "Conventions": "CF-1.11",
                "title": f"{plan.provider} {plan.model} forecast",
                "dataset_id": plan.dataset_id,
                "provider": plan.provider,
                "model": plan.model,
                "forecast_reference_time": plan.run_utc.isoformat(),
                "longitude_convention": plan.grid.longitude_convention,
                "source_manifest_sha256": report.manifest_hash,
                "input_hash": report.input_hash,
                "conversion_software": "forecast-zarr-processor",
                "conversion_version": __version__,
                "license": report.license,
                "attribution": report.attribution,
            }
        )
        coordinates = root.create_group("coordinates")
        root.create_group("surface")
        root.create_group("derived")
        root.create_group("provenance")
        compressor = [ZstdCodec(level=config.compression_level)]
        time_values = np.asarray(
            [_epoch_seconds(value) for value in plan.valid_times], dtype=np.int64
        )
        time_array = coordinates.create_array(
            "valid_time",
            data=time_values,
            chunks=(min(64, max(1, len(time_values))),),
            compressors=compressor,
        )
        time_array.attrs.update(
            {
                "_ARRAY_DIMENSIONS": ["valid_time"],
                "standard_name": "time",
                "long_name": "forecast valid time",
                "units": "seconds since 1970-01-01 00:00:00 UTC",
                "calendar": "proleptic_gregorian",
            }
        )
        latitude = coordinates.create_array(
            "latitude",
            data=np.asarray(plan.grid.latitude, dtype=np.float64),
            chunks=(min(720, len(plan.grid.latitude)),),
            compressors=compressor,
        )
        latitude.attrs.update(
            {
                "_ARRAY_DIMENSIONS": ["latitude"],
                "standard_name": "latitude",
                "units": "degrees_north",
                "axis": "Y",
            }
        )
        longitude = coordinates.create_array(
            "longitude",
            data=np.asarray(plan.grid.longitude, dtype=np.float64),
            chunks=(min(720, len(plan.grid.longitude)),),
            compressors=compressor,
        )
        longitude.attrs.update(
            {
                "_ARRAY_DIMENSIONS": ["longitude"],
                "standard_name": "longitude",
                "units": "degrees_east",
                "axis": "X",
            }
        )
        shape = (len(plan.valid_times), len(plan.grid.latitude), len(plan.grid.longitude))
        for variable in plan.variables:
            group = cast(zarr.Group, root[variable.group])
            dtype = np.dtype(variable.encoding.dtype)
            array = group.create_array(
                variable.name,
                shape=shape,
                chunks=variable.layout.chunks,
                shards=variable.layout.shards,
                dtype=dtype,
                fill_value=variable.encoding.fill_value,
                compressors=compressor,
            )
            attrs: dict[str, Any] = {
                "_ARRAY_DIMENSIONS": ["valid_time", "latitude", "longitude"],
                "units": variable.units,
                "long_name": variable.long_name,
                "source_grib_parameters": list(variable.source_short_names),
                "source_grib_levels": list(variable.source_levels),
                "forecast_reference_time": plan.run_utc.isoformat(),
                "grid_mapping": "regular_latitude_longitude",
                "conversion_method": "forecast-zarr-processor streaming ecCodes",
                "conversion_version": __version__,
                "license": report.license,
                "attribution": report.attribution,
                "_FillValue": variable.encoding.fill_value,
                "maximum_absolute_error": variable.encoding.maximum_absolute_error,
            }
            if variable.standard_name:
                attrs["standard_name"] = variable.standard_name
            if variable.name == "precipitation_amount":
                attrs["cell_methods"] = "time: sum"
                attrs["source_interval_selection"] = "latest startStep ending at valid_time"
            if variable.encoding.scale_factor is not None:
                attrs["scale_factor"] = variable.encoding.scale_factor
                attrs["add_offset"] = variable.encoding.add_offset
            if variable.encoding.fallback_reason:
                attrs["encoding_fallback_reason"] = variable.encoding.fallback_reason
            array.attrs.update(attrs)
        return cls(root, plan)

    @classmethod
    def open(
        cls,
        path: Path,
        plan: ProcessingPlan,
        *,
        mode: Literal["r", "r+", "a", "w", "w-"] = "r+",
    ) -> ForecastStore:
        root = zarr.open_group(store=path, mode=mode, zarr_format=3)
        if root.attrs.get("dataset_id") != plan.dataset_id:
            raise InputContractError("staging store belongs to another dataset")
        return cls(root, plan)

    def array(self, variable: VariablePlan) -> zarr.Array[Any]:
        group = cast(zarr.Group, self.root[variable.group])
        return cast(zarr.Array[Any], group[variable.name])

    def write_block(
        self,
        variable: VariablePlan,
        valid_time: datetime,
        source_latitude: npt.NDArray[np.float64],
        source_longitude: npt.NDArray[np.float64],
        physical_values: npt.NDArray[np.float64],
    ) -> None:
        """Write the intersection with the planned grid and reject conflicting overlap."""
        time_index = self.time_index.get(valid_time)
        if time_index is None:
            raise InputContractError(f"message time is absent from plan: {valid_time.isoformat()}")
        lat_positions = np.searchsorted(self.latitude, source_latitude)
        lon_positions = np.searchsorted(self.longitude, source_longitude)
        lat_valid = (lat_positions < self.latitude.size) & np.isclose(
            self.latitude[np.minimum(lat_positions, self.latitude.size - 1)], source_latitude
        )
        lon_valid = (lon_positions < self.longitude.size) & np.isclose(
            self.longitude[np.minimum(lon_positions, self.longitude.size - 1)], source_longitude
        )
        if not lat_valid.any() or not lon_valid.any():
            return
        selected_lat = np.flatnonzero(lat_valid)
        selected_lon = np.flatnonzero(lon_valid)
        target_lat = lat_positions[lat_valid]
        target_lon = lon_positions[lon_valid]
        if not (
            np.array_equal(target_lat, np.arange(target_lat[0], target_lat[-1] + 1))
            and np.array_equal(target_lon, np.arange(target_lon[0], target_lon[-1] + 1))
        ):
            raise InputContractError("source block maps non-contiguously onto target grid")
        values = physical_values[np.ix_(selected_lat, selected_lon)]
        encoded = encode_values(values, variable.encoding)
        selection = (
            time_index,
            slice(int(target_lat[0]), int(target_lat[-1]) + 1),
            slice(int(target_lon[0]), int(target_lon[-1]) + 1),
        )
        array = self.array(variable)
        existing = np.asarray(array[selection])
        fill = variable.encoding.fill_value
        empty = (
            np.isnan(existing) if isinstance(fill, float) and np.isnan(fill) else existing == fill
        )
        if (~empty).any():
            conflict = (~empty) & ~np.isclose(existing, encoded, rtol=0, atol=0, equal_nan=True)
            if conflict.any():
                raise InputContractError(
                    f"conflicting duplicate data for {variable.name} at {valid_time.isoformat()}"
                )
        merged = existing.copy()
        merged[empty] = encoded[empty]
        array[selection] = merged
