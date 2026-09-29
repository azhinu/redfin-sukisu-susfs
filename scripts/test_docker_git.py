"""Exercise build-container Git trust with simulated foreign source ownership."""

import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), pathlib.Path(__file__).with_name(name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


configure_git = load_script("configure-docker-git")
sync_stock = load_script("sync-stock")


class DockerGitTrustTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="redfin-git-trust-")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.repo = self.root / "workspace"
        self.evolution = self.root / "evolution-kernel"
        self.env = dict(
            os.environ,
            GIT_CONFIG_GLOBAL=str(self.root / "gitconfig"),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_COUNT="0",
        )
        self.env.pop("GIT_TEST_ASSUME_DIFFERENT_OWNER", None)
        self.init_repo(self.repo)
        self.init_repo(self.evolution)
        self.init_repo(self.root / "untrusted")
        self.git(
            "-c",
            "protocol.file.allow=always",
            "-C",
            self.repo,
            "submodule",
            "add",
            "--name",
            "build",
            self.evolution,
            "deps/build",
        )
        self.record = {
            "name": "build",
            "path": "build",
            "repository": str(self.evolution),
            "revision": self.git(
                "-C", self.evolution, "rev-parse", "HEAD"
            ).stdout.strip(),
        }
        (self.repo / "configs").mkdir()
        (self.repo / "configs/dependencies.json").write_text(json.dumps([self.record]))
        self.env["GIT_TEST_ASSUME_DIFFERENT_OWNER"] = "1"

    def git(self, *args, check=True):
        return subprocess.run(
            ["git", *map(str, args)],
            env=self.env,
            text=True,
            capture_output=True,
            check=check,
        )

    def init_repo(self, directory):
        self.git("init", "-q", directory)
        self.git(
            "-C",
            directory,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "Fixture",
            "--allow-empty",
        )

    def test_mounted_sources_validate_and_clone_without_trusting_other_repos(self):
        refused = self.git(
            "-C", self.repo, "ls-files", "--stage", "--", "deps/build", check=False
        )
        self.assertEqual(refused.returncode, 128)
        self.assertIn("detected dubious ownership", refused.stderr)

        with mock.patch.dict(os.environ, self.env, clear=True):
            configure_git.configure(self.repo, self.evolution)
        with mock.patch.object(sync_stock, "REPO", self.repo), mock.patch.object(
            sync_stock, "GIT_ENV", dict(self.env, GIT_ALLOW_PROTOCOL="file")
        ):
            sync_stock.validate([self.record])

        for index, source in enumerate(
            (self.repo / ".git/modules/build", self.repo / "deps/build", self.evolution)
        ):
            self.git(
                "clone",
                "--shared",
                "--no-checkout",
                source,
                self.root / f"clone-{index}",
            )

        refused = self.git("-C", self.root / "untrusted", "status", check=False)
        self.assertEqual(refused.returncode, 128)
        self.assertIn("detected dubious ownership", refused.stderr)


if __name__ == "__main__":
    unittest.main()
