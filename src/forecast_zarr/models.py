"""Input-contract, inventory, and processing-plan models."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceFile(BaseModel):
    """One validated artifact from forecast-ingest schema 1.x."""

    model_config = ConfigDict(extra="allow", frozen=True)

    name: str = Field(min_length=1)
    url: str = ""
    size: int = Field(ge=0)
    checksum: str
    forecast_step: int = Field(ge=0)
    status: Literal["validated"]
    etag: str | None = None
    completed_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        if Path(value).name != value or value.endswith(".part"):
            raise ValueError("file name must be a safe final artifact name")
        return value

    @field_validator("checksum")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        prefix, separator, digest = value.partition(":")
        if separator != ":" or prefix != "sha256" or len(digest) != 64:
            raise ValueError("checksum must use sha256:<64 hex characters>")
        try:
            int(digest, 16)
        except ValueError as error:
            raise ValueError("checksum digest must be hexadecimal") from error
        return value.lower()


class ExpectedSourceField(BaseModel):
    """Exact field identity embedded by forecast-ingest schema 1.1."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    short_name: str
    type_of_level: str
    level: str
    step_type: str | None = None
    discipline: int | None = None
    parameter_category: int | None = None
    parameter_number: int | None = None


class SourceManifest(BaseModel):
    """Actual public forecast-ingest handoff document."""

    model_config = ConfigDict(extra="allow", frozen=True)

    schema_version: str
    provider: str
    model: str
    run_utc: datetime
    original_request: dict[str, Any]
    applied_plan: dict[str, Any]
    files: tuple[SourceFile, ...] = Field(min_length=1)
    variables: tuple[str, ...]
    unsupported_variables: tuple[str, ...] = ()
    levels: tuple[str, ...] = ()
    forecast_steps: tuple[int, ...]
    regions: tuple[dict[str, Any], ...]
    spatial_method: str
    status: Literal["complete"]
    operations: dict[str, Any]
    license: str
    source: str
    attribution: str
    application_version: str
    eccodes_version: str

    @model_validator(mode="after")
    def supported_schema_and_consistent_steps(self) -> SourceManifest:
        major = self.schema_version.split(".", maxsplit=1)[0]
        if major != "1":
            raise ValueError(f"unsupported manifest schema version: {self.schema_version}")
        file_steps = {item.forecast_step for item in self.files}
        if not file_steps.issubset(set(self.forecast_steps)):
            raise ValueError("file forecast steps are absent from forecast_steps")
        names = [item.name for item in self.files]
        if len(names) != len(set(names)):
            raise ValueError("manifest contains duplicate file names")
        return self

    def expected_parameters(self, name: str) -> frozenset[str]:
        """Read the per-file ecCodes short names embedded in applied_plan."""
        raw_files = self.applied_plan.get("files", [])
        if not isinstance(raw_files, list):
            return frozenset()
        for raw in raw_files:
            if isinstance(raw, dict) and raw.get("name") == name:
                values = raw.get("expected_parameters", [])
                if isinstance(values, (list, tuple)):
                    return frozenset(str(value) for value in values)
        return frozenset()

    def expected_fields(self, name: str) -> tuple[ExpectedSourceField, ...]:
        """Read exact per-file field identities embedded in schema 1.1 plans."""
        raw_files = self.applied_plan.get("files", [])
        if not isinstance(raw_files, list):
            return ()
        for raw in raw_files:
            if not isinstance(raw, dict) or raw.get("name") != name:
                continue
            values = raw.get("expected_fields", [])
            if not isinstance(values, (list, tuple)):
                return ()
            return tuple(ExpectedSourceField.model_validate(value) for value in values)
        return ()


class MessageMeta(BaseModel):
    """Small ecCodes-derived description of one GRIB message."""

    model_config = ConfigDict(frozen=True)

    file_name: str
    message_index: int = Field(ge=0)
    short_name: str
    type_of_level: str
    level: float
    units: str
    valid_time: datetime
    forecast_reference_time: datetime
    forecast_step: int = Field(ge=0)
    step_type: str = "instant"
    start_step: int = Field(default=0, ge=0)
    end_step: int = Field(default=0, ge=0)
    discipline: int | None = None
    parameter_category: int | None = None
    parameter_number: int | None = None
    grid_type: str
    ni: int = Field(gt=0)
    nj: int = Field(gt=0)
    minimum: float | None = None
    maximum: float | None = None

    @property
    def identity(self) -> str:
        return (
            f"{self.short_name}:{self.type_of_level}:{self.level:g}:"
            f"{self.step_type}:{self.valid_time.isoformat()}"
        )

    @property
    def source_key(self) -> str:
        return f"{self.file_name}:{self.message_index}"


class VariableInventory(BaseModel):
    """Normalized field availability and observed range."""

    model_config = ConfigDict(frozen=True)

    name: str
    source_short_names: tuple[str, ...]
    source_levels: tuple[str, ...]
    units: str
    valid_times: tuple[datetime, ...]
    minimum: float | None = None
    maximum: float | None = None
    duplicate_count: int = 0


class GridInventory(BaseModel):
    """Regular grid geometry after coordinate normalization."""

    model_config = ConfigDict(frozen=True)

    grid_type: Literal["regular_ll"]
    latitude: tuple[float, ...]
    longitude: tuple[float, ...]
    longitude_convention: Literal["-180_180", "0_360"]


class InspectionReport(BaseModel):
    """Validated, normalized inventory used as the plan input."""

    model_config = ConfigDict(frozen=True)

    input_dir: Path
    manifest_path: Path
    manifest_hash: str
    input_hash: str
    provider: str
    model: str
    run_utc: datetime
    source_files: tuple[SourceFile, ...]
    messages: tuple[MessageMeta, ...]
    variables: tuple[VariableInventory, ...]
    missing_variables: tuple[str, ...]
    unknown_messages: tuple[str, ...]
    grid: GridInventory
    license: str
    attribution: str


class ArrayEncoding(BaseModel):
    """Physical-to-storage encoding selected before conversion."""

    model_config = ConfigDict(frozen=True)

    dtype: Literal["int16", "float32"]
    fill_value: int | float
    scale_factor: float | None = None
    add_offset: float | None = None
    maximum_absolute_error: float
    fallback_reason: str | None = None


class ArrayLayout(BaseModel):
    """Zarr v3 inner chunks and outer shards."""

    model_config = ConfigDict(frozen=True)

    chunks: tuple[int, int, int]
    shards: tuple[int, int, int]
    uncompressed_shard_bytes: int


class VariablePlan(BaseModel):
    """Storage decision for one normalized variable."""

    model_config = ConfigDict(frozen=True)

    name: str
    required: bool = False
    group: Literal["surface", "height_80m", "height_100m", "atmosphere"]
    units: str
    standard_name: str | None
    long_name: str
    source_short_names: tuple[str, ...]
    source_levels: tuple[str, ...]
    valid_times: tuple[datetime, ...]
    encoding: ArrayEncoding
    layout: ArrayLayout


class BudgetReport(BaseModel):
    """Conservative resource estimate and pass/fail decision."""

    model_config = ConfigDict(frozen=True)

    estimated_output_bytes: int
    estimated_temporary_bytes: int
    estimated_peak_memory_bytes: int
    current_free_bytes: int
    projected_free_bytes: int
    passes: bool
    reasons: tuple[str, ...]


class ProcessingPlan(BaseModel):
    """Complete non-mutating result of the plan stage."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    input_hash: str
    provider: str
    model: str
    run_utc: datetime
    output_path: Path
    staging_path: Path
    variables: tuple[VariablePlan, ...]
    valid_times: tuple[datetime, ...]
    grid: GridInventory
    encoding_mode: Literal["lossless", "api_compact"]
    budget: BudgetReport
    warnings: tuple[str, ...]
