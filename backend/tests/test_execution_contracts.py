from __future__ import annotations

from pathlib import Path
import unittest

from app.config import Settings
from app.execution import ExecutionService
from app.execution.errors import InvalidInputError, NotFoundError, PermissionDeniedError, normalize_error


class ExecutionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_capability_routing(self):
        service = ExecutionService(Settings())
        calls = []

        async def read(*args): calls.append(("read", args)); return {}
        async def glob(*args): calls.append(("glob", args)); return {}
        async def execute(*args): calls.append(("bash", args)); return {}
        async def apply(*args): calls.append(("apply_patch", args)); return {}

        service.filesystem.read = read
        service.search.glob = glob
        service.shell.execute = execute
        service.patch.apply = apply
        await service.read("x")
        await service.glob("*.py")
        await service.bash("echo ok")
        await service.apply_patch("*** Begin Patch\n*** End Patch")
        self.assertEqual([name for name, _ in calls], ["read", "glob", "bash", "apply_patch"])

    def test_error_normalization_preserves_stable_categories(self):
        self.assertIsInstance(normalize_error(FileNotFoundError("missing")), NotFoundError)
        self.assertIsInstance(normalize_error(PermissionError("denied")), PermissionDeniedError)
        self.assertIsInstance(normalize_error(ValueError("bad input")), InvalidInputError)

    def test_execution_modules_have_no_transport_imports(self):
        root = Path(__file__).parents[1] / "app" / "execution"
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("fastapi", text.lower())
            self.assertNotIn("fastmcp", text.lower())

if __name__ == "__main__":
    unittest.main()
