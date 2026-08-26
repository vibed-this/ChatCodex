from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pytest

from app.config import Settings
from app.execution import ExecutionService
from app.execution.errors import ExecutionError


class PatchUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_hunk_does_not_mutate_any_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("one\n", encoding="utf-8")
            second.write_text("two\n", encoding="utf-8")
            patch = (
                "*** Begin Patch\n"
                f"*** Update File: {first}\n"
                "@@\n-one\n+ONE\n"
                f"*** Update File: {second}\n"
                "@@\n-not-present\n+TWO\n"
                "*** End Patch\n"
            )
            service = ExecutionService(Settings())
            with pytest.raises(ExecutionError):
                await service.apply_patch(patch)
            assert first.read_text(encoding="utf-8") == "one\n"
            assert second.read_text(encoding="utf-8") == "two\n"
