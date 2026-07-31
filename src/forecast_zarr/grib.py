"""Sequential ecCodes reader with no whole-dataset materialization."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from forecast_zarr.errors import DependencyMissingError, InputContractError, UnsupportedGridError
from forecast_zarr.models import MessageMeta


@dataclass(frozen=True)
class DecodedMessage:
    """One independently decoded GRIB message."""

    meta: MessageMeta
    latitudes: npt.NDArray[np.float64]
    longitudes: npt.NDArray[np.float64]
    values: npt.NDArray[np.float64]


class GribReader(Protocol):
    """Injectable interface used by tests and the conversion pipeline."""

    def iter_file(self, path: Path) -> Iterator[DecodedMessage]: ...

    def version(self) -> str: ...


class EccodesReader:
    """Decode one message at a time through the official ecCodes bindings."""

    def __init__(self) -> None:
        try:
            import eccodes
        except ImportError as error:
            raise DependencyMissingError(
                "ecCodes Python bindings are required; see docs/ubuntu-deployment.md"
            ) from error
        self._api: Any = eccodes

    def version(self) -> str:
        value = getattr(self._api, "codes_get_api_version", lambda: "unknown")()
        return str(value)

    def iter_file(self, path: Path) -> Iterator[DecodedMessage]:
        with path.open("rb") as stream:
            index = 0
            while (message_id := self._api.codes_grib_new_from_file(stream)) is not None:
                try:
                    yield self._decode(message_id, path.name, index)
                except Exception as error:
                    if isinstance(error, InputContractError):
                        raise
                    raise InputContractError(
                        f"failed to decode {path.name} message {index}: {error}"
                    ) from error
                finally:
                    self._api.codes_release(message_id)
                index += 1
        if index == 0:
            raise InputContractError(f"GRIB file has no messages: {path}")

    def _get(self, message_id: int, key: str, default: Any = None) -> Any:
        try:
            return self._api.codes_get(message_id, key)
        except Exception:
            return default

    def _decode(self, message_id: int, file_name: str, index: int) -> DecodedMessage:
        grid_type = str(self._get(message_id, "gridType", "unknown"))
        if grid_type != "regular_ll":
            raise UnsupportedGridError(f"unsupported_grid_type: {grid_type} in {file_name}")
        date = int(self._get(message_id, "dataDate"))
        time = int(self._get(message_id, "dataTime", 0))
        reference = datetime.strptime(f"{date:08d}{time:04d}", "%Y%m%d%H%M").replace(tzinfo=UTC)
        validity_date = int(self._get(message_id, "validityDate", date))
        validity_time = int(self._get(message_id, "validityTime", time))
        try:
            valid = datetime.strptime(
                f"{validity_date:08d}{validity_time:04d}", "%Y%m%d%H%M"
            ).replace(tzinfo=UTC)
        except ValueError:
            valid = reference + timedelta(hours=int(self._get(message_id, "endStep", 0)))
        values = np.asarray(self._api.codes_get_values(message_id), dtype=np.float64)
        missing_value = self._get(message_id, "missingValue")
        if missing_value is not None:
            values[np.isclose(values, float(missing_value))] = np.nan
        latitudes = np.asarray(self._api.codes_get_array(message_id, "latitudes"), dtype=np.float64)
        longitudes = np.asarray(
            self._api.codes_get_array(message_id, "longitudes"), dtype=np.float64
        )
        if not (values.size == latitudes.size == longitudes.size):
            raise InputContractError("values and coordinate arrays have different sizes")
        finite = values[np.isfinite(values)]
        meta = MessageMeta(
            file_name=file_name,
            message_index=index,
            short_name=str(self._get(message_id, "shortName", "unknown")),
            type_of_level=str(self._get(message_id, "typeOfLevel", "unknown")),
            level=float(self._get(message_id, "level", 0)),
            units=str(self._get(message_id, "units", "1")),
            valid_time=valid,
            forecast_reference_time=reference,
            forecast_step=max(0, round((valid - reference).total_seconds() / 3600)),
            step_type=str(self._get(message_id, "stepType", "instant")),
            start_step=max(0, int(self._get(message_id, "startStep", 0))),
            end_step=max(0, int(self._get(message_id, "endStep", 0))),
            grid_type=grid_type,
            ni=int(self._get(message_id, "Ni", 0)),
            nj=int(self._get(message_id, "Nj", 0)),
            minimum=float(finite.min()) if finite.size else None,
            maximum=float(finite.max()) if finite.size else None,
        )
        return DecodedMessage(meta, latitudes, longitudes, values)
