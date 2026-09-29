"""Regression gates for patch application and host device-test orchestration."""

import contextlib
import importlib.util
import io
import json
import os
import shlex
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from device_test import Device, check_manager_log, sha256_file


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), Path(__file__).with_name(name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


apply = load_script("apply-sukisu-susfs")
connected = load_script("test-connected-redfin")
MANAGER_LOG = (
    "PhantomProcessRecord abc com.sukisu.ultra:root:0/0}\n"
    "com.sukisu.ultra:root:0: System.exit called, status: 0\n"
    "Susfs { command: Status }\nSusfs { command: Version }\n"
)
INSTALLED = "4.19.325-cip126-st10-g40601b47a2c5"


class PatchApplicationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="redfin-migration-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.file = self.root / "example"
        self.file.write_text("old\n")
        self.patch = self.root / "change.patch"
        self.patch.write_text(
            "diff --git a/example b/example\n--- a/example\n+++ b/example\n@@ -1 +1 @@\n-old\n+new\n"
        )

    def test_checked_application_and_repeat_preserve_source(self):
        with contextlib.redirect_stdout(io.StringIO()):
            apply.apply_once(self.root, self.patch, "Test patch")
            apply.apply_once(self.root, self.patch, "Test patch")
        self.assertEqual(self.file.read_text(), "new\n")

    def test_conflicting_patch_leaves_source_untouched(self):
        self.file.write_text("local change\n")
        with self.assertRaisesRegex(RuntimeError, "does not apply cleanly"):
            apply.apply_once(self.root, self.patch, "Test patch")
        self.assertEqual(self.file.read_text(), "local change\n")

    def test_install_refuses_modified_destination(self):
        destination = self.root / "installed"
        destination.write_text("modified\n")
        with self.assertRaisesRegex(RuntimeError, "Refusing to overwrite"):
            apply.install_checked(self.file, destination)
        self.assertEqual(destination.read_text(), "modified\n")

    def test_missing_environment_fails_before_git(self):
        with mock.patch.object(apply, "git") as git:
            with self.assertRaisesRegex(ValueError, "KERNEL_DIR is required"):
                apply.Integration({})
            git.assert_not_called()

    def test_patch_override_and_occupied_driver_path(self):
        integration = apply.Integration(
            {
                "KERNEL_DIR": str(self.root),
                "SUKISU_SOURCE_DIR": str(self.root),
                "SUSFS_SOURCE_DIR": str(self.root),
                "REPO_ROOT": str(self.root),
                "KERNEL_API_PATCH_FILE": str(self.patch),
            }
        )
        self.assertEqual(
            integration.patches["kernel_integration_patch"], self.patch.resolve()
        )
        (self.root / "drivers/kernelsu").mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, "non-symlink"):
            integration.link_driver()


class FakeDevice(Device):
    """Small device model: root control sees real metadata, app UID sees rules."""

    def __init__(self):
        super().__init__("test-serial")
        self.kernel = "test-kernel"
        self.boot_id = "temporary-boot"
        self.hidden = False
        self.spoofed = False
        self.redirected = False
        self.commands = []
        self.fault = False
        self.uname_timeout = False

    def call(self, *args, check=True, timeout=30):
        self.commands.append(args)
        code = 0
        output = ""
        if args[0] == "get-state":
            output = "device\n"
        elif args[0] == "logcat":
            output = MANAGER_LOG
        elif args[0] == "reboot":
            self.kernel = INSTALLED
            self.boot_id = "installed-boot"
        elif args[0] == "shell":
            command = " ".join(map(str, args[1:]))
            if command == "uname -r":
                output = self.kernel
            elif command == "getprop ro.boot.bootreason":
                output = "reboot,bootloader"
            elif command == "getprop sys.boot_completed":
                output = "1"
            elif command == "cat /proc/sys/kernel/random/boot_id":
                output = self.boot_id
            elif command == "id -u":
                output = "0"
            elif command == "dmesg":
                output = "Kernel panic" if self.fault else "Kernel running"
            elif command.startswith("-tt "):
                output = "uid=0(root)\n/dev/pts/0\n"
            elif " susfs status" in command:
                output = "true\n"
            elif " susfs version" in command:
                output = "1.5.5\n"
            elif " susfs set-uname " in command:
                release = shlex.split(command)[3]
                self.kernel = "test-kernel" if release == "default" else release
                if self.uname_timeout and release != "default":
                    raise subprocess.TimeoutExpired("adb", 30)
            elif " susfs add-open-redirect " in command:
                self.redirected = True
            elif command.startswith("cat ") and command.endswith("/target"):
                output = "redirected" if self.redirected else "original"
            elif " susfs add-sus-path " in command:
                self.hidden = True
            elif " susfs add-sus-kstat-statically " in command:
                self.spoofed = True
            elif shlex.split(command)[0].endswith("/test-app-uid-stat"):
                _, uid, path = shlex.split(command)
                output = f"uid={uid}\n"
                if path.endswith("hide-target") and self.hidden and uid != "0":
                    code = 1
                    output += "stat_errno=2\n"
                else:
                    size = 7 if path.endswith("hide-target") else 4
                    inode = 1
                    if path.endswith("kstat-target") and self.spoofed and uid != "0":
                        size, inode = 424242, 7654321
                    output += f"stat_size={size}\nstat_ino={inode}\n"
        result = subprocess.CompletedProcess(args, code, output, "")
        if check and code:
            raise RuntimeError("Fake ADB failure.")
        return result

    def wait(self, timeout):
        pass


class DeviceGateTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="redfin-device-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        (self.artifacts / "fastboot").mkdir()
        for path in (self.artifacts / "boot.img", self.artifacts / "fastboot/boot.img"):
            path.write_bytes(b"test boot")
        (self.artifacts / "kernel-release.txt").write_text("test-kernel\n")
        (self.artifacts / "kernel.config").write_text(
            "CONFIG_KSU=y\nCONFIG_KSU_SUSFS=y\n"
        )
        with zipfile.ZipFile(
            self.artifacts / "AnyKernel-redfin-sukisu.zip", "w"
        ) as archive:
            archive.writestr("Image.lz4", b"kernel")
        patch = (
            connected.ROOT
            / "patches/sukisu-v4.2.0-evolution-4.19-file-wrapper-lsm-blob.patch"
        )
        (self.artifacts / "sukisu-susfs.lock").write_text(
            f"SUKISU_V420_EVOLUTION_FILE_WRAPPER_PATCH_SHA256={sha256_file(patch)}\n"
        )
        self.checksums()
        self.report = self.root / "report"
        self.report.mkdir()
        self.previous = self.root / "previous"
        self.previous.mkdir()
        (self.previous / "boot-id.txt").write_text("temporary-boot\n")
        self.boot_report = self.previous / "boot-test.json"
        self.boot_report.write_text(
            json.dumps(
                {
                    "passed": True,
                    "sha256": sha256_file(self.artifacts / "boot.img"),
                    "expected_kernel": "test-kernel",
                }
            )
        )
        args = SimpleNamespace(
            serial="test-serial",
            artifacts=self.artifacts,
            report=self.report,
            skip_build=True,
            resume=True,
            pty_iterations=3,
        )
        self.test = connected.ConnectedTest(
            args, {"TEST_BOOT_REPORT": str(self.boot_report)}
        )
        self.device = FakeDevice()
        self.test.device = self.device

    def checksums(self):
        (self.artifacts / "SHA256SUMS").write_text(
            "".join(
                f"{sha256_file(path)}  {path.relative_to(self.artifacts)}\n"
                for path in sorted(self.artifacts.rglob("*"))
                if path.is_file() and path.name != "SHA256SUMS"
            )
        )

    def test_complete_device_gate_and_return_to_installed_kernel(self):
        with mock.patch.object(self.test, "run_logged"), mock.patch(
            "device_test.time.sleep"
        ), contextlib.redirect_stdout(io.StringIO()):
            self.test.run()
            self.test.cleanup(False)
        self.assertEqual(self.device.kernel, INSTALLED)
        self.assertFalse(self.test.rules_changed)
        self.assertEqual(
            sum(command[:2] == ("shell", "-tt") for command in self.device.commands), 3
        )
        self.assertIn(
            "Device test completed", (self.report / "summary.txt").read_text()
        )
        self.assertTrue(
            self.device.hidden and self.device.spoofed and self.device.redirected
        )

    def test_build_passes_container_artifact_path_to_shell_launcher(self):
        self.test.args.resume = False
        self.test.args.skip_build = False
        with mock.patch.object(self.test, "run_logged") as run, mock.patch.object(
            connected, "ROOT", self.root
        ), mock.patch("device_test.time.sleep"), contextlib.redirect_stdout(
            io.StringIO()
        ):
            self.test.run()
        build = next(call for call in run.call_args_list if call.args[1] == "build.log")
        self.assertEqual(
            build.kwargs["env"]["PACKAGE_ARTIFACT_DIR"], "/workspace/artifacts"
        )
        self.assertTrue(
            any(call.args[1] == "boot-test.log" for call in run.call_args_list)
        )

    def test_build_rejects_unmounted_artifact_directory(self):
        with self.assertRaisesRegex(RuntimeError, "inside the repository"):
            connected.container_artifact_dir(self.root / "outside", self.root)
        self.assertEqual(
            connected.container_artifact_dir(self.root / "artifacts/custom", self.root),
            "/workspace/artifacts/custom",
        )

    def test_resume_rejects_another_boot_before_manager_or_rules(self):
        self.device.boot_id = "unverified-boot"
        with mock.patch.object(self.test, "run_logged"), contextlib.redirect_stdout(
            io.StringIO()
        ):
            with self.assertRaisesRegex(RuntimeError, "boot ID differs"):
                self.test.run()
        self.assertFalse(
            any(" susfs " in str(command) for command in self.device.commands)
        )

    def test_kernel_fault_prevents_stateful_probes(self):
        self.device.fault = True
        with mock.patch.object(self.test, "run_logged"), mock.patch(
            "device_test.time.sleep"
        ), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "Kernel fault markers"):
                self.test.run()
        self.assertFalse(
            self.device.hidden or self.device.spoofed or self.device.redirected
        )

    def test_cleanup_restores_uname_after_command_timeout(self):
        self.test.kernel = "test-kernel"
        self.device.uname_timeout = True
        with self.assertRaises(subprocess.TimeoutExpired):
            self.test.test_susfs("/data/local/tmp/test")
        self.assertTrue(self.test.uname_changed)
        with mock.patch.object(self.test, "run_logged"):
            self.test.cleanup(True)
        self.assertEqual(self.device.kernel, "test-kernel")

    def test_cleanup_reboots_after_stateful_rules_failure(self):
        self.test.rules_changed = True
        self.test.probe_dir = "/data/local/tmp/test"
        with mock.patch.object(self.test, "run_logged"):
            self.test.cleanup(True)
        self.assertIn(("reboot",), self.device.commands)
        self.assertIn(("shell", "rm -rf /data/local/tmp/test"), self.device.commands)

    def test_checksums_reject_changed_boot(self):
        (self.artifacts / "boot.img").write_bytes(b"changed boot")
        with self.assertRaisesRegex(RuntimeError, "SHA256 check failed"):
            connected.validate_artifacts(self.artifacts)

    def test_checksums_reject_path_escape(self):
        (self.artifacts / "SHA256SUMS").write_text("0" * 64 + "  ../outside\n")
        with self.assertRaisesRegex(RuntimeError, "escapes artifact directory"):
            connected.validate_artifacts(self.artifacts)

    def test_resume_rejects_failed_or_different_image(self):
        for overrides in (
            {"passed": False},
            {"sha256": "wrong"},
            {"expected_kernel": "wrong"},
        ):
            report = {
                "passed": True,
                "sha256": "sha",
                "expected_kernel": "kernel",
                **overrides,
            }
            self.boot_report.write_text(json.dumps(report))
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                connected.validate_resume(
                    self.boot_report, "sha", "kernel", "temporary-boot"
                )

    def test_manager_requires_uid_zero_success_and_no_path_errors(self):
        check_manager_log(MANAGER_LOG)
        for log in (
            MANAGER_LOG.replace("root:0/0}", "root:0/2000}"),
            MANAGER_LOG.replace("status: 0", "status: 1"),
            MANAGER_LOG + "ksud::cli: Error: /data/adb/denied",
        ):
            with self.assertRaises(RuntimeError):
                check_manager_log(log)


if __name__ == "__main__":
    unittest.main()
