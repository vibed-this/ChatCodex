# Copyright (c) 2026 ChatCodex contributors.
"""Structured errors for the execution layer."""

from __future__ import annotations

from typing import Any


class ExecutionError(Exception):
    """Base error with stable machine-readable semantics."""

    code = "execution_error"
    retryable = False

    def __init__(
        self, message: str, *args: Any, hint: str = "", retryable: bool | None = None
    ) -> None:
        # Accept the legacy (code, message, hint) shape during the migration so
        # adapters can normalize old capability implementations without leaking
        # the old exception type across the boundary.
        if args:
            if len(args) > 2:
                msg = "ExecutionError accepts at most code, message, hint"
                raise TypeError(msg)
            code = str(message)
            if len(args) == 1:
                message, hint = str(args[0]), message
            else:
                message, hint = str(args[0]), str(args[1])
            self.code = code
        super().__init__(message)
        self.message = message
        self.hint = hint
        if retryable is not None:
            self.retryable = retryable


class NotFoundError(ExecutionError):
    code = "not_found"


class PermissionDeniedError(ExecutionError):
    code = "permission_denied"


class InvalidInputError(ExecutionError):
    code = "invalid_input"


class ConflictError(ExecutionError):
    code = "conflict"


class TimeoutError(ExecutionError):
    code = "timeout"
    retryable = True


class OutputLimitError(ExecutionError):
    code = "output_limit"


class BackendUnavailableError(ExecutionError):
    code = "backend_unavailable"
    retryable = True


_ERROR_TYPES = {
    "not_found": NotFoundError,
    "permission_denied": PermissionDeniedError,
    "invalid_input": InvalidInputError,
    "invalid_pattern": InvalidInputError,
    "invalid_edit": InvalidInputError,
    "invalid_timeout": InvalidInputError,
    "invalid_plan": InvalidInputError,
    "invalid_path": InvalidInputError,
    "invalid_patch": InvalidInputError,
    "multiple_matches": ConflictError,
    "out_of_range": InvalidInputError,
    "is_directory": InvalidInputError,
    "binary": InvalidInputError,
    "invalid_regex": InvalidInputError,
    "conflict": ConflictError,
    "timeout": TimeoutError,
    "search_timeout": TimeoutError,
    "output_limit": OutputLimitError,
    "read_error": BackendUnavailableError,
    "write_error": BackendUnavailableError,
    "delete_error": BackendUnavailableError,
    "glob_error": BackendUnavailableError,
    "search_error": BackendUnavailableError,
    "bash_error": BackendUnavailableError,
    "patch_commit_failed": BackendUnavailableError,
    "backend_unavailable": BackendUnavailableError,
}


def normalize_error(exc: Exception) -> ExecutionError:
    if isinstance(exc, ExecutionError):
        error_type = _ERROR_TYPES.get(exc.code, ExecutionError)
        if type(exc) is error_type:
            return exc
        return error_type(str(exc), hint=getattr(exc, "hint", ""))
    if isinstance(exc, FileNotFoundError):
        return NotFoundError(str(exc))
    if isinstance(exc, PermissionError):
        return PermissionDeniedError(str(exc))
    if isinstance(exc, (ValueError, TypeError)):
        return InvalidInputError(str(exc))
    return BackendUnavailableError(str(exc), retryable=False)
