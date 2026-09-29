"""Focused tests for isolated, pinned dependency staging."""

import contextlib
import importlib.util
import io
import pathlib
import tempfile
import unittest
from unittest import mock

SCRIPT = pathlib.Path(__file__).with_name("sync-stock.py")
SPEC = importlib.util.spec_from_file_location("sync_stock", SCRIPT)
sync_stock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_stock)


class SyncStockTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.repo = pathlib.Path(self.tempdir.name)
        (self.repo / ".git" / "modules" / "kernel").mkdir(parents=True)
        (self.repo / "deps" / "kernel" / ".git").mkdir(parents=True)
        self.old_repo = sync_stock.REPO
        sync_stock.REPO = self.repo
        self.addCleanup(setattr, sync_stock, "REPO", self.old_repo)

    def test_repository_prefers_object_store_over_dirty_checkout(self):
        self.assertEqual(
            sync_stock.repository("kernel"), self.repo / ".git" / "modules" / "kernel"
        )

    def test_validate_uses_pinned_object_and_only_warns_about_dirty_checkout(self):
        revision = "a" * 40
        record = {
            "name": "kernel",
            "path": "kernel/google_redbull",
            "revision": revision,
            "repository": "https://example.invalid/kernel.git",
        }
        object_store = self.repo / ".git" / "modules" / "kernel"

        def fake_run(*args):
            if args[3:5] == ("ls-files", "--stage"):
                return f"160000 {revision} 0\tdeps/kernel"
            if "cat-file" in args:
                self.assertEqual(args[1], f"--git-dir={object_store}")
                self.assertEqual(args[-1], f"{revision}^{{commit}}")
                return ""
            if "status" in args:
                self.assertIn(str(self.repo / "deps" / "kernel"), args)
                return " M locally-changed-file"
            self.fail(f"Unexpected command: {args}")

        modules = {"kernel": {"path": "deps/kernel", "url": record["repository"]}}
        stderr = io.StringIO()
        with mock.patch.object(
            sync_stock, "submodules", return_value=modules
        ), mock.patch.object(
            sync_stock, "run", side_effect=fake_run
        ), contextlib.redirect_stderr(
            stderr
        ):
            sync_stock.validate([record])

        self.assertIn(
            "worktree has local changes and is excluded from staging", stderr.getvalue()
        )

    def test_clear_stage_root_removes_manifest_managed_targets(self):
        root = self.repo / "stock"
        target = root / "build"
        target.mkdir(parents=True)
        (target / "stale-file").write_text("stale\n")
        (root / "source-lock.json").write_text("{}\n")

        sync_stock.clear_stage_root([{"path": "build"}], root)

        self.assertFalse(target.exists())
        self.assertFalse((root / "source-lock.json").exists())


if __name__ == "__main__":
    unittest.main()
