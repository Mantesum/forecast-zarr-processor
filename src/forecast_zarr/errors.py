"""Typed failures and stable process exit codes."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Exit codes suitable for systemd units and shell automation."""

    OK = 0
    CONFIGURATION = 2
    INPUT_INVALID = 3
    UNSUPPORTED = 4
    BUDGET_EXCEEDED = 5
    CONVERSION_FAILED = 6
    VALIDATION_FAILED = 7
    DEPENDENCY_MISSING = 8


class ProcessorError(Exception):
    """Base error carrying a stable machine-facing code."""

    exit_code = ExitCode.CONVERSION_FAILED
    reason = "processor_error"


class ConfigurationError(ProcessorError):
    exit_code = ExitCode.CONFIGURATION
    reason = "configuration_error"


class InputContractError(ProcessorError):
    exit_code = ExitCode.INPUT_INVALID
    reason = "input_contract_error"


class UnsupportedGridError(ProcessorError):
    exit_code = ExitCode.UNSUPPORTED
    reason = "unsupported_grid_type"


class BudgetExceededError(ProcessorError):
    exit_code = ExitCode.BUDGET_EXCEEDED
    reason = "disk_budget_exceeded"


class ValidationError(ProcessorError):
    exit_code = ExitCode.VALIDATION_FAILED
    reason = "validation_error"


class DependencyMissingError(ProcessorError):
    exit_code = ExitCode.DEPENDENCY_MISSING
    reason = "dependency_missing"
