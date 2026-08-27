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


BATCH_TOOL_DEFINITION = ToolDefinition(
    "batch_call",
    "Call multiple MCP tools in one request, preserving input order and returning each result independently. For parallel background work, put multiple shell_spawn calls first and then shell_wait calls immediately after them so several shells start without waiting between starts. Do not invoke batch_call recursively.",
    _schema(
        {
            "calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "arguments": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["name", "arguments"],
                    "additionalProperties": False,
                },
            }
        },
        ["calls"],
    ),
    {
        "type": "object",
        "properties": {"results": {"type": "array"}},
        "required": ["results"],
    },
)

SHELL_SPAWN_TOOL_DEFINITION = ToolDefinition(
    "shell_spawn",
    "Start a local shell command in the background and return immediately. stdout and stderr are redirected directly to the returned temporary outputPath; use read or grep on that file instead of expecting command output here.",
    _schema(
        {"command": {"type": "string"}, "workdir": {"type": ["string", "null"]}},
        ["command"],
    ),
    {"type": "object", "additionalProperties": True},
)

SHELL_KILL_TOOL_DEFINITION = ToolDefinition(
    "shell_kill",
    "Kill a background shell identified by shellId and its child process tree.",
    _schema({"shellId": {"type": "string"}}, ["shellId"]),
    {"type": "object", "additionalProperties": True},
)

SHELL_WAIT_TOOL_DEFINITION = ToolDefinition(
    "shell_wait",
    "Wait for a background shell to terminate. timeout is optional milliseconds; when it expires, return immediately without killing the shell. The result includes terminationReason: process_exit (with exitCode), wait_timeout, user_terminated_process, or user_terminated_wait (with terminationDetail), plus outputPath so the AI can read the temporary output file directly.",
    _schema(
        {"shellId": {"type": "string"}, "timeout": {"type": ["integer", "null"]}},
        ["shellId"],
    ),
    {
        "type": "object",
        "properties": {
            "shellId": {"type": "string"},
            "pid": {"type": ["integer", "null"]},
            "command": {"type": "string"},
            "outputPath": {"type": "string"},
            "running": {"type": "boolean"},
            "exitCode": {"type": ["integer", "null"]},
            "timedOut": {"type": "boolean"},
            "terminationReason": {
                "type": "string",
                "enum": [
                    "running",
                    "process_exit",
                    "wait_timeout",
                    "user_terminated_process",
                    "user_terminated_wait",
                ],
            },
            "terminationDetail": {"type": "string"},
            "startedAt": {"type": "number"},
            "finishedAt": {"type": ["number", "null"]},
        },
        "required": ["shellId", "outputPath", "running", "exitCode", "timedOut", "terminationReason"],
        "additionalProperties": False,
    },
)


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
        "Execute a local shell command synchronously and wait for it to finish. bash is synchronously blocking. For ordinary commands this is appropriate; for long-running commands, background work, or resident tasks, always use shell_spawn instead, then shell_wait as needed. Command output from background shells is redirected to the returned temporary outputPath and should be read with read or grep.",
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

TOOL_DEFINITIONS = {
    definition.name: definition
    for definition in (
        *CORE_TOOL_DEFINITIONS,
        BATCH_TOOL_DEFINITION,
        SHELL_SPAWN_TOOL_DEFINITION,
        SHELL_KILL_TOOL_DEFINITION,
        SHELL_WAIT_TOOL_DEFINITION,
    )
}
