#!/usr/bin/env python3
"""Build and exercise one temporary Evolution X redfin boot without flashing."""

import argparse
import contextlib
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from device_test import Device, sha256_file, test_manager

ROOT = Path(__file__).resolve().parent.parent
FAULT = re.compile(
    r"Kernel panic|kernel BUG at|BUG: unable to handle kernel|Oops:|Unable to handle kernel|list_del corruption"
)
BAD_BOOT = "089e6f0767e9286a02b019a3c3e3c6afb88370601cdb682066523c1c572a4045"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate_artifacts(directory, repo=ROOT):
    for name in (
        "boot.img",
        "kernel-release.txt",
        "kernel.config",
        "SHA256SUMS",
        "AnyKernel-redfin-sukisu.zip",
        "fastboot/boot.img",
        "sukisu-susfs.lock",
    ):
        require((directory / name).is_file(), f"Missing artifact: {name}.")
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
        require(match is not None, "Invalid SHA256SUMS entry.")
        expected, name = match.groups()
        path = (directory / name).resolve()
        require(
            path.is_relative_to(directory.resolve()),
            "Checksum path escapes artifact directory.",
        )
        require(
            sha256_file(path) == expected.lower(),
            f"Artifact SHA256 check failed: {name}.",
        )
    require((directory / "SHA256SUMS").stat().st_size > 0, "SHA256SUMS is empty.")
    with zipfile.ZipFile(directory / "AnyKernel-redfin-sukisu.zip") as archive:
        require(archive.testzip() is None, "AnyKernel ZIP is corrupt.")
    boot_sha = sha256_file(directory / "boot.img")
    require(
        boot_sha == sha256_file(directory / "fastboot/boot.img"),
        "Fastboot boot copy differs.",
    )
    config = (directory / "kernel.config").read_text().splitlines()
    for symbol in ("CONFIG_KSU=y", "CONFIG_KSU_SUSFS=y"):
        require(symbol in config, f"{symbol} is missing.")
    kernel = (directory / "kernel-release.txt").read_text().strip()
    require(bool(kernel), "Kernel release is empty.")
    require(boot_sha != BAD_BOOT, "This boot SHA is known to panic on PTY su.")
    patch = repo / "patches/sukisu-v4.2.0-evolution-4.19-file-wrapper-lsm-blob.patch"
    require(patch.is_file(), "Evolution file-wrapper fix is missing.")
    require(
        f"SUKISU_V420_EVOLUTION_FILE_WRAPPER_PATCH_SHA256={sha256_file(patch)}"
        in (directory / "sukisu-susfs.lock").read_text().splitlines(),
        "Artifact lock does not contain the current Evolution file-wrapper fix.",
    )
    return kernel, boot_sha


def container_artifact_dir(directory, root=ROOT):
    artifacts = (root / "artifacts").resolve()
    directory = directory.resolve()
    require(
        directory.is_relative_to(artifacts),
        "Build artifacts must be inside the repository artifacts directory; use --skip-build for external files.",
    )
    return str(Path("/workspace/artifacts") / directory.relative_to(artifacts))


def validate_resume(report, boot_sha, kernel, current_boot_id):
    previous = json.loads(report.read_text())
    require(
        previous.get("passed") is True
        and previous.get("sha256") == boot_sha
        and previous.get("expected_kernel") == kernel,
        "Previous boot report does not match this exact image.",
    )
    boot_id = (report.parent / "boot-id.txt").read_text().strip()
    require(
        bool(boot_id) and boot_id == current_boot_id,
        "Current boot ID differs from the verified temporary boot.",
    )


class ConnectedTest:
    def __init__(self, args, env):
        self.args = args
        self.env = env
        self.device = Device(args.serial)
        self.artifacts = args.artifacts.resolve()
        self.report = args.report.resolve()
        self.probe_dir = ""
        self.uname_changed = False
        self.rules_changed = False
        self.ksud = "/data/adb/ksu/bin/ksud"
        self.kernel = ""

    def record(self, kind, message):
        text = f"{kind}: {message}\n"
        print(text, end="", flush=True)
        with (self.report / "summary.txt").open("a") as stream:
            stream.write(text)

    def run_logged(self, command, name, env=None):
        with (self.report / name).open("w") as log:
            subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )

    def adb_logged(self, name, *args, check=True, append=False):
        result = self.device.call(*args, check=False)
        with (self.report / name).open("a" if append else "w") as stream:
            stream.write(result.stdout + result.stderr)
        if check:
            require(
                result.returncode == 0, f"ADB command failed; see {self.report / name}."
            )
        return result

    def alive(self):
        require(
            self.device.call("get-state").stdout.strip() == "device",
            "ADB disconnected; inspect bootreason and pstore.",
        )
        kernel = self.device.shell("uname -r")
        reason = self.device.shell("getprop ro.boot.bootreason")
        require(
            kernel == self.kernel, f"Kernel changed: {kernel} (bootreason: {reason})."
        )
        require(
            "panic" not in reason and "watchdog" not in reason,
            f"Bad bootreason: {reason}.",
        )

    def kernel_log(self, name, fault_name):
        result = self.adb_logged(name, "shell", "dmesg")
        faults = [line for line in result.stdout.splitlines() if FAULT.search(line)]
        (self.report / fault_name).write_text(
            "\n".join(faults) + ("\n" if faults else "")
        )
        require(not faults, f"Kernel fault markers found; see {name}.")

    def probe(self, name, path, uid=10000, success=True, fields=None):
        command = f"{shlex.quote(self.probe_dir + '/test-app-uid-stat')} {uid} {shlex.quote(path)}"
        result = self.adb_logged(name, "shell", command, check=False)
        require(
            (result.returncode == 0) == success,
            f"Unexpected app-UID probe result; see {name}.",
        )
        lines = result.stdout.splitlines()
        require(f"uid={uid}" in lines, f"Probe did not enter UID {uid}; see {name}.")
        for key, value in (fields or {}).items():
            require(f"{key}={value}" in lines, f"Unexpected {key}; see {name}.")

    def run(self):
        self.record("INFO", f"Serial={self.args.serial}; report={self.report}")
        if not self.args.skip_build and not self.args.resume:
            self.run_logged(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "scripts",
                    "-p",
                    "test_*.py",
                ],
                "unit-tests.log",
            )
            self.record("PASS", "Source unit tests passed.")
            build_env = dict(
                self.env,
                JOBS=self.env.get("JOBS") or "3",
                PACKAGE_ARTIFACT_DIR=container_artifact_dir(self.artifacts, ROOT),
            )
            self.run_logged(
                [str(ROOT / "scripts/build-evolution-susfs.sh")],
                "build.log",
                env=build_env,
            )
            self.record("PASS", "Kernel build completed.")
        else:
            self.record(
                "SKIP", "Build was skipped by request; using existing artifacts."
            )
        self.kernel, boot_sha = validate_artifacts(self.artifacts)
        (self.report / "checksums.log").write_text("Artifact SHA256 check passed.\n")
        (self.report / "zip.log").write_text("AnyKernel ZIP check passed.\n")
        (self.report / "boot.sha256").write_text(
            f"{boot_sha}  {self.artifacts / 'boot.img'}\n"
        )
        self.record(
            "PASS", "Artifacts, kernel config, SHA256, ZIP, and fastboot copy verified."
        )
        self.run_logged(["go", "version"], "go-version.txt")
        go_env = dict(
            self.env,
            GOTOOLCHAIN="local",
            GOPROXY="off",
            GOOS="linux",
            GOARCH="arm64",
            CGO_ENABLED="0",
        )
        self.run_logged(
            [
                "go",
                "build",
                "-trimpath",
                "-ldflags=-s -w",
                "-o",
                str(self.report / "test-app-uid-stat"),
                str(ROOT / "scripts/test-app-uid-stat.go"),
            ],
            "probe-build.log",
            env=go_env,
        )
        if self.args.resume:
            previous = self.env.get("TEST_BOOT_REPORT")
            require(
                bool(previous),
                "Set TEST_BOOT_REPORT to the previous successful boot-test.json for --resume.",
            )
            require(
                self.device.shell("getprop sys.boot_completed") == "1",
                "Android is not fully booted.",
            )
            validate_resume(
                Path(previous),
                boot_sha,
                self.kernel,
                self.device.shell("cat /proc/sys/kernel/random/boot_id"),
            )
            self.record(
                "SKIP", "Temporary boot was already verified by TEST_BOOT_REPORT."
            )
        else:
            self.run_logged(
                [
                    sys.executable,
                    str(ROOT / "scripts/test-boot.py"),
                    "--serial",
                    self.args.serial,
                    "--image",
                    str(self.artifacts / "boot.img"),
                    "--expected-kernel",
                    self.kernel,
                    "--timeout",
                    self.env.get("BOOT_TIMEOUT") or "240",
                    "--report",
                    str(self.report / "boot-test.json"),
                ],
                "boot-test.log",
            )
        self.alive()
        boot_id = self.device.shell("cat /proc/sys/kernel/random/boot_id")
        require(bool(boot_id), "Cannot record boot ID.")
        (self.report / "boot-id.txt").write_text(boot_id + "\n")
        self.record("PASS", "Android is booted on the expected kernel.")
        self.adb_logged(
            "logcat-before-manager.log", "logcat", "-d", "-b", "all", check=False
        )
        with (self.report / "manager.log").open("w") as log, contextlib.redirect_stdout(
            log
        ):
            test_manager(self.device)
        self.alive()
        self.record("PASS", "Manager launched its UID 0 rootserver.")
        self.adb_logged("adb-root.log", "root", check=False)
        self.device.wait(90)
        if self.device.shell("id -u") != "0":
            require(
                sys.stdin.isatty(),
                "ADB Root is disabled; toggle it off/on in Manager and rerun with --resume and TEST_BOOT_REPORT from this run.",
            )
            input("Toggle ADB Root off/on in Manager, then press Enter here.\n")
            self.adb_logged("adb-root.log", "root", check=False, append=True)
            self.device.wait(90)
        require(self.device.shell("id -u") == "0", "ADB shell did not become UID 0.")
        self.record("PASS", "SukiSU ADB Root gives UID 0.")
        self.device.shell(f"test -x {self.ksud}")
        self.probe_dir = (
            f"/data/local/tmp/redfin_probe_{int(time.time())}_{os.getpid()}"
        )
        directory = shlex.quote(self.probe_dir)
        self.device.shell(f"mkdir -p {directory} && chmod 755 {directory}")
        self.adb_logged(
            "probe-push.log",
            "push",
            self.report / "test-app-uid-stat",
            self.probe_dir + "/test-app-uid-stat",
        )
        self.device.shell(
            f"chmod 755 {directory}/test-app-uid-stat && ln -s {self.ksud} {directory}/su"
        )
        for attempt in range(1, self.args.pty_iterations + 1):
            result = self.adb_logged(
                f"pty-su-{attempt}.log", "shell", "-tt", f"{directory}/su -c 'id; tty'"
            )
            require(
                "uid=0(root)" in result.stdout and "/dev/pts/" in result.stdout,
                f"PTY su attempt {attempt} did not report root with a PTY.",
            )
            self.alive()
            self.kernel_log(f"dmesg-after-pty-{attempt}.log", "pty-kernel-faults.log")
            self.record(
                "PASS",
                f"PTY su attempt {attempt} returned UID 0, closed, and kernel stayed alive.",
            )
        status = self.adb_logged(
            "susfs-status.log", "shell", f"{self.ksud} susfs status"
        )
        version = self.adb_logged(
            "susfs-version.log", "shell", f"{self.ksud} susfs version"
        )
        require("true" in status.stdout.splitlines(), "SUSFS status was not true.")
        require("1.5.5" in version.stdout, "SUSFS version was not 1.5.5.")
        self.record("PASS", "Direct SUSFS status=true and version=1.5.5.")
        self.test_susfs(directory)
        self.kernel_log("dmesg-final.log", "kernel-faults.log")
        self.record("PASS", "Final kernel log has no panic, Oops, or fatal BUG marker.")
        self.record(
            "SKIP",
            "Classic su compatibility and unsupported SUSFS commands are not claimed.",
        )
        self.rollback(boot_id, directory)
        self.record("PASS", f"Device test completed; diagnostics: {self.report}")

    def test_susfs(self, directory):
        require(
            self.device.shell("uname -r") == self.kernel,
            "UNAME is already spoofed; refusing to overwrite it.",
        )
        release = f"susfs_probe_{int(time.time())}"
        # Set cleanup flags before mutations: a timeout can occur after the
        # kernel accepted a command but before ADB returned its result.
        self.uname_changed = True
        self.adb_logged(
            "uname.log", "shell", f"{self.ksud} susfs set-uname {release} default"
        )
        require(
            self.device.shell("uname -r") == release,
            "SUSFS UNAME had no visible effect.",
        )
        self.adb_logged(
            "uname.log",
            "shell",
            f"{self.ksud} susfs set-uname default default",
            append=True,
        )
        self.uname_changed = False
        self.alive()
        self.record("PASS", "SUSFS UNAME changed and restored uname -r.")
        self.device.shell(
            f"printf original > {directory}/target && printf redirected > {directory}/source"
        )
        require(
            self.device.shell(f"cat {directory}/target") == "original",
            "Redirect baseline is wrong.",
        )
        self.rules_changed = True
        self.adb_logged(
            "redirect.log",
            "shell",
            f"{self.ksud} susfs add-open-redirect {directory}/target {directory}/source 2",
        )
        require(
            self.device.shell(f"cat {directory}/target") == "redirected",
            "SUSFS OPEN_REDIRECT had no visible effect.",
        )
        self.alive()
        self.record(
            "PASS", "SUSFS OPEN_REDIRECT changed bytes read through the target path."
        )
        self.device.shell(
            f"printf visible > {directory}/hide-target && printf real > {directory}/kstat-target && chmod 644 {directory}/hide-target {directory}/kstat-target"
        )
        hide = self.probe_dir + "/hide-target"
        stat = self.probe_dir + "/kstat-target"
        self.probe("sus-path-before.log", hide, fields={"stat_size": 7})
        self.adb_logged(
            "sus-path-command.log",
            "shell",
            f"{self.ksud} susfs add-sus-path {directory}/hide-target",
        )
        self.probe("sus-path-after.log", hide, success=False, fields={"stat_errno": 2})
        self.probe("sus-path-root.log", hide, uid=0)
        self.record(
            "PASS", "SUS_PATH hid the target from app UID while root retained access."
        )
        self.probe("kstat-before.log", stat, fields={"stat_size": 4})
        self.adb_logged(
            "kstat-command.log",
            "shell",
            f"{self.ksud} susfs add-sus-kstat-statically {directory}/kstat-target 7654321 1 1 424242 0 0 0 0 0 0 1 4096",
        )
        self.probe(
            "kstat-after.log", stat, fields={"stat_size": 424242, "stat_ino": 7654321}
        )
        self.probe("kstat-root.log", stat, uid=0, fields={"stat_size": 4})
        self.alive()
        self.record(
            "PASS", "SUS_KSTAT spoofed size for app UID while root retained real size."
        )

    def rollback(self, boot_id, directory):
        self.record(
            "INFO", "Rebooting to installed kernel to discard temporary SUSFS rules."
        )
        self.adb_logged("cleanup.log", "shell", f"rm -rf {directory}", append=True)
        self.probe_dir = ""
        self.alive()
        self.device.call("reboot")
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            try:
                new_id = self.device.shell("cat /proc/sys/kernel/random/boot_id")
                completed = self.device.shell("getprop sys.boot_completed")
                if new_id and new_id != boot_id and completed == "1":
                    break
            except (RuntimeError, subprocess.SubprocessError):
                pass
            time.sleep(2)
        else:
            raise RuntimeError(
                "Device did not complete a new boot after cleanup reboot."
            )
        self.rules_changed = False
        kernel = self.device.shell("uname -r")
        reason = self.device.shell("getprop ro.boot.bootreason")
        require(
            kernel
            == (
                self.env.get("EXPECTED_INSTALLED_KERNEL")
                or "4.19.325-cip126-st10-g40601b47a2c5"
            ),
            f"Installed kernel mismatch after reboot: {kernel}.",
        )
        require(
            "panic" not in reason and "watchdog" not in reason,
            f"Bad rollback bootreason: {reason}.",
        )
        self.record(
            "PASS",
            f"Installed Evolution kernel booted after cleanup: {kernel} ({reason}).",
        )

    def cleanup(self, failed):
        if failed:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    if self.device.shell("getprop sys.boot_completed") == "1":
                        break
                except (RuntimeError, subprocess.SubprocessError):
                    pass
                time.sleep(2)
        commands = [
            ("logcat.log", ("logcat", "-d", "-b", "all")),
            ("dmesg.log", ("shell", "dmesg")),
            (
                "pstore.log",
                (
                    "shell",
                    "cat /sys/fs/pstore/console-ramoops* /proc/last_kmsg 2>/dev/null",
                ),
            ),
            ("bootreason.txt", ("shell", "getprop ro.boot.bootreason")),
        ]
        if failed:
            commands.append(
                (
                    "last-kmsg-dropbox.log",
                    ("shell", "dumpsys dropbox --print SYSTEM_LAST_KMSG"),
                )
            )
        if self.uname_changed:
            commands.append(
                (
                    "cleanup.log",
                    ("shell", f"{self.ksud} susfs set-uname default default"),
                )
            )
        if self.probe_dir:
            commands.append(
                ("cleanup.log", ("shell", f"rm -rf {shlex.quote(self.probe_dir)}"))
            )
        if self.rules_changed and failed:
            commands.append(("cleanup.log", ("reboot",)))
        for name, command in commands:
            try:
                self.adb_logged(
                    name, *command, check=False, append=name == "cleanup.log"
                )
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                with (self.report / name).open("a") as stream:
                    stream.write(f"Diagnostic collection failed: {error}\n")
        try:
            self.run_logged(["fastboot", "devices"], "fastboot-devices.txt")
        except (OSError, subprocess.SubprocessError):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--skip-build", action="store_true")
    mode.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--serial", default=os.environ.get("ADB_SERIAL", "09181FDD400301")
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=os.environ.get(
            "TEST_ARTIFACT_DIR", ROOT / "artifacts/evolution-susfs-v420"
        ),
    )
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parser.add_argument(
        "--report",
        type=Path,
        default=os.environ.get(
            "TEST_REPORT_DIR", ROOT / f"artifacts/device-test-{stamp}"
        ),
    )
    parser.add_argument(
        "--pty-iterations",
        type=int,
        choices=range(1, 11),
        default=os.environ.get("PTY_ITERATIONS", "3"),
    )
    args = parser.parse_args()
    if args.pty_iterations not in range(1, 11):
        parser.error("PTY_ITERATIONS must be between 1 and 10.")
    for tool in ("adb", "fastboot", "go"):
        if not shutil.which(tool):
            parser.error(f"Missing tool: {tool}.")
    args.report.mkdir(parents=True, exist_ok=True)
    test = ConnectedTest(args, os.environ)
    status = 1
    try:
        test.run()
        status = 0
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
        EOFError,
    ) as error:
        test.record("FAIL", str(error))
    except KeyboardInterrupt:
        test.record("FAIL", "Interrupted by user.")
        status = 130
    finally:
        test.cleanup(status != 0)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
