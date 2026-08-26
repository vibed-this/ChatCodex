from __future__ import annotations

import importlib
import os
import tempfile
import unittest


class BackendSmokeTests(unittest.TestCase):
    def test_application_and_mcp_can_be_created(self):
        with tempfile.TemporaryDirectory() as directory:
            old = os.environ.get("CHATCODEX_DATABASE_URL")
            os.environ["CHATCODEX_DATABASE_URL"] = f"sqlite:///{directory}/smoke.db"
            os.environ["CHATCODEX_MCP_AUTH_MODE"] = "noauth"
            try:
                main = importlib.import_module("app.main")
                self.assertIsNotNone(main.app)
                self.assertIsNone(main.mcp)
                self.assertIsNone(main.runtime)
            finally:
                if "main" in locals() and getattr(main, "runtime", None) is not None:
                    main.runtime.close()
                if old is None:
                    os.environ.pop("CHATCODEX_DATABASE_URL", None)
                else:
                    os.environ["CHATCODEX_DATABASE_URL"] = old


    def test_runtime_factory_builds_dependencies_without_import_time_singleton(self):
        with tempfile.TemporaryDirectory() as directory:
            old = os.environ.get("CHATCODEX_DATABASE_URL")
            os.environ["CHATCODEX_DATABASE_URL"] = f"sqlite:///{directory}/factory.db"
            os.environ["CHATCODEX_MCP_AUTH_MODE"] = "noauth"
            try:
                from app.runtime import create_runtime
                runtime = create_runtime()
                self.assertIsNotNone(runtime.execution)
                self.assertIsNotNone(runtime.mcp)
                runtime.close()
            finally:
                if old is None:
                    os.environ.pop("CHATCODEX_DATABASE_URL", None)
                else:
                    os.environ["CHATCODEX_DATABASE_URL"] = old


if __name__ == "__main__":
    unittest.main()
