from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, cast

from app.config import Settings
from app.execution import ExecutionService
from app.execution.errors import (
    InvalidInputError,
    NotFoundError,
    PermissionDeniedError,
    normalize_error,
)


class ExecutionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_capability_routing(self) -> None:
        service = ExecutionService(Settings())
        calls = []

        async def read(*args: Any) -> dict[str, Any]:
            calls.append(("read", args))
            return {}

        async def glob(*args: Any) -> dict[str, Any]:
            calls.append(("glob", args))
            return {}

        async def execute(*args: Any) -> dict[str, Any]:
            calls.append(("bash", args))
            return {}

        async def apply(*args: Any) -> dict[str, Any]:
            calls.append(("apply_patch", args))
            return {}

        cast("Any", service.filesystem).read = read
        cast("Any", service.search).glob = glob
        cast("Any", service.shell).execute = execute
        cast("Any", service.patch).apply = apply
        await service.read("x")
        await service.glob("*.py")
        await service.bash("echo ok")
        await service.apply_patch("*** Begin Patch\n*** End Patch")
        assert [name for name, _ in calls] == ["read", "glob", "bash", "apply_patch"]

    def test_error_normalization_preserves_stable_categories(self) -> None:
        assert isinstance(normalize_error(FileNotFoundError("missing")), NotFoundError)
        assert isinstance(
            normalize_error(PermissionError("denied")), PermissionDeniedError
        )
        assert isinstance(normalize_error(ValueError("bad input")), InvalidInputError)

    def test_execution_modules_have_no_transport_imports(self) -> None:
        root = Path(__file__).parents[1] / "app" / "execution"
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "fastapi" not in text.lower()
            assert "fastmcp" not in text.lower()


if __name__ == "__main__":
    unittest.main()
