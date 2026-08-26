from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.config import Settings
from app.execution import ExecutionService
from app.execution.errors import ExecutionError


class PatchUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_hunk_does_not_mutate_any_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("one\n", encoding="utf-8")
            second.write_text("two\n", encoding="utf-8")
            patch = (
                "*** Begin Patch\n"
                + f"*** Update File: {first}\n"
                + "@@\n-one\n+ONE\n"
                + f"*** Update File: {second}\n"
                + "@@\n-not-present\n+TWO\n"
                + "*** End Patch\n"
            )
            service = ExecutionService(Settings())
            with self.assertRaises(ExecutionError):
                await service.apply_patch(patch)
            self.assertEqual(first.read_text(encoding="utf-8"), "one\n")
            self.assertEqual(second.read_text(encoding="utf-8"), "two\n")
