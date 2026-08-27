from __future__ import annotations

import asyncio
import importlib
import os
import tempfile
import unittest


class BackendSmokeTests(unittest.TestCase):
    def test_application_and_mcp_can_be_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old = os.environ.get("CHATCODEX_DATABASE_URL")
            os.environ["CHATCODEX_DATABASE_URL"] = f"sqlite:///{directory}/smoke.db"
            os.environ["CHATCODEX_MCP_AUTH_MODE"] = "noauth"
            try:
                main = importlib.import_module("app.main")
                assert main.app is not None
                assert main.mcp is None
                assert main.runtime is None
            finally:
                runtime = getattr(locals().get("main"), "runtime", None)
                if runtime is not None:
                    asyncio.run(runtime.close())
                if old is None:
                    os.environ.pop("CHATCODEX_DATABASE_URL", None)
                else:
                    os.environ["CHATCODEX_DATABASE_URL"] = old

    def test_runtime_factory_builds_dependencies_without_import_time_singleton(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old = os.environ.get("CHATCODEX_DATABASE_URL")
            os.environ["CHATCODEX_DATABASE_URL"] = f"sqlite:///{directory}/factory.db"
            os.environ["CHATCODEX_MCP_AUTH_MODE"] = "noauth"
            try:
                from app.runtime import create_runtime

                runtime = create_runtime()
                assert runtime.execution is not None
                assert runtime.mcp is not None
                asyncio.run(runtime.close())
            finally:
                if old is None:
                    os.environ.pop("CHATCODEX_DATABASE_URL", None)
                else:
                    os.environ["CHATCODEX_DATABASE_URL"] = old


if __name__ == "__main__":
    unittest.main()
