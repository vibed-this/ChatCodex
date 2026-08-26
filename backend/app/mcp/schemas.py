# Copyright (c) 2026 ChatCodex contributors.
"""Transport-independent MCP tool definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None


CORE_TOOL_NAMES = frozenset(
    {"read", "write", "edit", "glob", "grep", "bash", "apply_patch"}
)


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


CORE_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "read",
        "Read a file or directory from the local filesystem.",
        _schema(
            {
                "filePath": {"type": "string"},
                "offset": {"type": ["integer", "null"]},
                "limit": {"type": ["integer", "null"]},
            },
            ["filePath"],
        ),
        {"type": "object", "additionalProperties": True},
    ),
    ToolDefinition(
        "write",
        "Write content to a file with full OS-level access.",
        _schema(
            {"filePath": {"type": "string"}, "content": {"type": "string"}},
            ["filePath", "content"],
        ),
        {"type": "object", "additionalProperties": True},
    ),
    ToolDefinition(
        "edit",
        "Replace exact text in a file with full OS-level access.",
        _schema(
            {
                "filePath": {"type": "string"},
                "oldString": {"type": "string"},
                "newString": {"type": "string"},
                "replaceAll": {"type": "boolean"},
            },
            ["filePath", "oldString", "newString"],
        ),
        {"type": "object", "additionalProperties": True},
    ),
    ToolDefinition(
        "glob",
        "Find files using a bounded recursive glob search.",
        _schema(
            {"pattern": {"type": "string"}, "path": {"type": ["string", "null"]}},
            ["pattern"],
        ),
        {"type": "object", "additionalProperties": True},
    ),
    ToolDefinition(
        "grep",
        "Search text with ripgrep when available and a bounded Python fallback.",
        _schema(
            {
                "pattern": {"type": "string"},
                "path": {"type": ["string", "null"]},
                "include": {"type": ["string", "null"]},
            },
            ["pattern"],
        ),
        {"type": "object", "additionalProperties": True},
    ),
    ToolDefinition(
        "bash",
        "Execute a local shell command with OS-level permissions; Windows uses PowerShell.",
        _schema(
            {
                "command": {"type": "string"},
                "timeout": {"type": ["integer", "null"]},
                "workdir": {"type": ["string", "null"]},
            },
            ["command"],
        ),
        {"type": "object", "additionalProperties": True},
    ),
    ToolDefinition(
        "apply_patch",
        "Parse, validate, calculate, and atomically commit a multi-file patch.",
        _schema({"patchText": {"type": "string"}}, ["patchText"]),
        {"type": "object", "additionalProperties": True},
    ),
)

TOOL_DEFINITIONS = {definition.name: definition for definition in CORE_TOOL_DEFINITIONS}
