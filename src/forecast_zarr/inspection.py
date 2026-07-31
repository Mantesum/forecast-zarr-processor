"""Discover and inspect a complete forecast-ingest run."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np

from forecast_zarr.config import ProcessorConfig
from forecast_zarr.errors import InputContractError, UnsupportedGridError
from forecast_zarr.grib import EccodesReader, GribReader
from forecast_zarr.hashing import sha256_json
from forecast_zarr.manifest import load_source_manifest
from forecast_zarr.models import (
    ExpectedSourceField,
    GridInventory,
    InspectionReport,
    MessageMeta,
    VariableInventory,
)
from forecast_zarr.normalization import (
    DERIVED_DEPENDENCIES,
    SPECS_BY_NAME,
    VariableSpec,
    accepts_step_type,
    match_variable,
    normalize_values,
    regular_grid,
)


def selected_message_keys(messages: tuple[MessageMeta, ...]) -> frozenset[str]:
    """Select one semantically preferred message per file, variable, and valid time."""
    grouped: dict[tuple[str, str, object], list[MessageMeta]] = defaultdict(list)
    for meta in messages:
        spec = match_message(meta)
        if spec is None or not accepts_step_type(spec, meta.step_type):
            continue
        grouped[(meta.file_name, spec.name, meta.valid_time)].append(meta)

    selected: set[str] = set()
    for (_file_name, variable_name, _valid_time), candidates in grouped.items():
        if variable_name == "precipitation_amount":
            preferred = max(candidates, key=lambda item: (item.start_step, -item.message_index))
            selected.add(preferred.source_key)
        else:
            selected.update(item.source_key for item in candidates)
    return frozenset(selected)


def _region_mask(
    axis: np.ndarray[Any, np.dtype[np.float64]],
    regions: tuple[dict[str, Any], ...],
    convention: str,
) -> np.ndarray[Any, np.dtype[np.bool_]]:
    if not regions:
        return np.ones(axis.shape, dtype=np.bool_)
    selected = np.zeros(axis.shape, dtype=np.bool_)
    for region in regions:
        if region.get("kind", "bbox") != "bbox":
            continue
        west = float(region["west"])
        east = float(region["east"])
        if west == -180 and east == 180:
            return np.ones(axis.shape, dtype=np.bool_)
        if convention == "0_360":
            west %= 360
            east %= 360
        if west <= east:
            selected |= (axis >= west - 1e-9) & (axis <= east + 1e-9)
        else:
            selected |= (axis >= west - 1e-9) | (axis <= east + 1e-9)
    return selected


def _latitude_mask(
    axis: np.ndarray[Any, np.dtype[np.float64]], regions: tuple[dict[str, Any], ...]
) -> np.ndarray[Any, np.dtype[np.bool_]]:
    if not regions:
        return np.ones(axis.shape, dtype=np.bool_)
    selected = np.zeros(axis.shape, dtype=np.bool_)
    for region in regions:
        if "south" in region and "north" in region:
            selected |= (axis >= float(region["south"]) - 1e-9) & (
                axis <= float(region["north"]) + 1e-9
            )
    return selected


def match_message(meta: MessageMeta) -> VariableSpec | None:
    return match_variable(
        meta.short_name,
        meta.type_of_level,
        meta.level,
        meta.discipline,
        meta.parameter_category,
        meta.parameter_number,
    )


def _matches_expected_field(expected: ExpectedSourceField, observed: MessageMeta) -> bool:
    try:
        level_matches = bool(np.isclose(float(expected.level), observed.level))
    except ValueError:
        level_matches = expected.level == f"{observed.level:g}"
    return bool(
        expected.short_name == observed.short_name
        and expected.type_of_level == observed.type_of_level
        and level_matches
        and (expected.step_type is None or expected.step_type == observed.step_type)
        and (expected.discipline is None or expected.discipline == observed.discipline)
        and (
            expected.parameter_category is None
            or expected.parameter_category == observed.parameter_category
        )
        and (
            expected.parameter_number is None
            or expected.parameter_number == observed.parameter_number
        )
    )


def inspect_run(
    config: ProcessorConfig,
    *,
    reader: GribReader | None = None,
) -> InspectionReport:
    """Validate source bytes and build an ecCodes-backed normalized inventory."""
    input_dir = config.input_run.resolve()
    manifest, manifest_path, manifest_hash = load_source_manifest(input_dir)
    decoder = reader or EccodesReader()
    messages = []
    unknown: list[str] = []
    observed_by_file: dict[str, set[str]] = defaultdict(set)
    messages_by_file: dict[str, list[MessageMeta]] = defaultdict(list)
    steps_by_file: dict[str, set[int]] = defaultdict(set)
    latitudes: set[float] = set()
    longitudes: set[float] = set()

    for source_file in manifest.files:
        path = input_dir / source_file.name
        for decoded in decoder.iter_file(path):
            meta = decoded.meta
            if meta.grid_type != "regular_ll":
                raise UnsupportedGridError(
                    f"unsupported_grid_type: {meta.grid_type} in {source_file.name}"
                )
            if meta.forecast_reference_time != manifest.run_utc:
                raise InputContractError(
                    f"forecast reference time mismatch in {source_file.name}: "
                    f"{meta.forecast_reference_time.isoformat()} != {manifest.run_utc.isoformat()}"
                )
            if meta.forecast_step != source_file.forecast_step:
                raise InputContractError(
                    f"forecast step mismatch in {source_file.name}: "
                    f"{meta.forecast_step} != {source_file.forecast_step}"
                )
            messages.append(meta)
            messages_by_file[source_file.name].append(meta)
            observed_by_file[source_file.name].add(meta.short_name)
            steps_by_file[source_file.name].add(meta.forecast_step)
            spec = match_message(meta)
            if spec is None:
                unknown.append(
                    f"{meta.short_name}:{meta.type_of_level}:{meta.level:g}:{meta.step_type}"
                )
                continue
            if not accepts_step_type(spec, meta.step_type):
                continue
            canonical = normalize_values(spec, decoded.values, meta.units)
            lat_axis, lon_axis, _ = regular_grid(
                decoded.latitudes,
                decoded.longitudes,
                canonical,
                convention=config.longitude_convention,
            )
            if config.crop_to_manifest_regions:
                lat_axis = lat_axis[_latitude_mask(lat_axis, manifest.regions)]
                lon_axis = lon_axis[
                    _region_mask(lon_axis, manifest.regions, config.longitude_convention)
                ]
            latitudes.update(float(value) for value in lat_axis)
            longitudes.update(float(value) for value in lon_axis)
        expected = manifest.expected_parameters(source_file.name)
        absent = expected - observed_by_file[source_file.name]
        if absent:
            raise InputContractError(
                f"{source_file.name} is missing manifest parameters: {sorted(absent)}"
            )
        exact_expected = manifest.expected_fields(source_file.name)
        absent_fields = tuple(
            field
            for field in exact_expected
            if not any(
                _matches_expected_field(field, observed)
                for observed in messages_by_file[source_file.name]
            )
        )
        if absent_fields:
            labels = [
                f"{field.short_name}@{field.type_of_level}:{field.level}/{field.step_type}"
                for field in absent_fields
            ]
            raise InputContractError(
                f"{source_file.name} is missing manifest fields: {sorted(labels)}"
            )
        if steps_by_file[source_file.name] != {source_file.forecast_step}:
            raise InputContractError(f"mixed or missing forecast steps in {source_file.name}")

    if not messages:
        raise InputContractError("source run contains no GRIB messages")
    if not latitudes or not longitudes:
        raise InputContractError("manifest regions do not intersect the GRIB grid")
    selected = selected_message_keys(tuple(messages))
    aggregates: dict[str, dict[str, Any]] = {}
    identities: dict[tuple[str, object], int] = defaultdict(int)
    for meta in messages:
        if meta.source_key not in selected:
            continue
        spec = match_message(meta)
        assert spec is not None
        item = aggregates.setdefault(
            spec.name,
            {
                "short_names": set(),
                "levels": set(),
                "valid_times": set(),
                "minimum": None,
                "maximum": None,
                "duplicates": 0,
            },
        )
        item["short_names"].add(meta.short_name)
        item["levels"].add(f"{meta.type_of_level}:{meta.level:g}")
        item["valid_times"].add(meta.valid_time)
        extrema = [value for value in (meta.minimum, meta.maximum) if value is not None]
        if extrema:
            canonical = normalize_values(spec, np.asarray(extrema, dtype=np.float64), meta.units)
            value_min = float(canonical.min())
            value_max = float(canonical.max())
            item["minimum"] = (
                value_min if item["minimum"] is None else min(item["minimum"], value_min)
            )
            item["maximum"] = (
                value_max if item["maximum"] is None else max(item["maximum"], value_max)
            )
        identity = (spec.name, meta.valid_time)
        identities[identity] += 1
        if identities[identity] > 1:
            item["duplicates"] += 1
    inventory = tuple(
        VariableInventory(
            name=name,
            source_short_names=tuple(sorted(item["short_names"])),
            source_levels=tuple(sorted(item["levels"])),
            units=SPECS_BY_NAME[name].units,
            valid_times=tuple(sorted(item["valid_times"])),
            minimum=item["minimum"],
            maximum=item["maximum"],
            duplicate_count=item["duplicates"],
        )
        for name, item in sorted(aggregates.items())
    )
    available = {item.name for item in inventory}
    direct_requested = {name for name in config.variables if name not in DERIVED_DEPENDENCIES}
    missing = tuple(sorted(direct_requested - available))
    input_hash = sha256_json(
        {
            "manifest": manifest_hash,
            "files": [(item.name, item.checksum) for item in manifest.files],
        }
    )
    return InspectionReport(
        input_dir=input_dir,
        manifest_path=manifest_path,
        manifest_hash=manifest_hash,
        input_hash=input_hash,
        provider=manifest.provider,
        model=manifest.model,
        run_utc=manifest.run_utc,
        source_files=manifest.files,
        messages=tuple(messages),
        variables=inventory,
        missing_variables=missing,
        unknown_messages=tuple(sorted(set(unknown))),
        grid=GridInventory(
            grid_type="regular_ll",
            latitude=tuple(sorted(latitudes)),
            longitude=tuple(sorted(longitudes)),
            longitude_convention=config.longitude_convention,
        ),
        license=manifest.license,
        attribution=manifest.attribution,
    )
