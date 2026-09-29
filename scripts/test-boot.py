#!/usr/bin/env python3
"""Temporarily boot one image and verify Android completes on the expected kernel."""

import argparse
import hashlib
import json
import pathlib
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--image", type=pathlib.Path, required=True)
    parser.add_argument("--expected-kernel", required=True)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--report", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if not args.image.is_file():
        parser.error("Boot image does not exist.")
    result = {
        "image": str(args.image),
        "sha256": hashlib.sha256(args.image.read_bytes()).hexdigest(),
        "expected_kernel": args.expected_kernel,
        "samples": [],
        "passed": False,
    }

    def call(tool, *command, timeout=15):
        return subprocess.run(
            [tool, "-s", args.serial, *command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )

    def adb_state():
        probe = subprocess.run(
            ["adb", "devices", "-l"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
        )
        for line in probe.stdout.splitlines():
            fields = line.split()
            if fields and fields[0] == args.serial and len(fields) >= 2:
                return fields[1]
        return None

    try:
        state = call("adb", "get-state")
        if state.returncode == 0 and state.stdout.strip() == "device":
            print("Rebooting the device to bootloader.", flush=True)
            call("adb", "reboot", "bootloader").check_returncode()
        ready = False
        for _ in range(30):
            devices = subprocess.run(
                ["fastboot", "devices"], capture_output=True, text=True, timeout=10
            )
            if args.serial in devices.stdout:
                ready = True
                break
            time.sleep(1)
        if not ready:
            raise RuntimeError("Device did not enter fastboot.")
        product = call("fastboot", "getvar", "product")
        if product.returncode or "product: redfin" not in product.stdout:
            raise RuntimeError("Fastboot target is not redfin.")
        print(f"Booting {args.image}.", flush=True)
        boot = call("fastboot", "boot", str(args.image), timeout=60)
        result["fastboot"] = boot.stdout
        print(boot.stdout, flush=True)
        boot.check_returncode()
        deadline = time.monotonic() + args.timeout
        boot_started = time.monotonic()
        last = None
        while time.monotonic() < deadline:
            state = adb_state()
            if state == "recovery":
                print(
                    "Recovery detected; returning to bootloader without wiping data.",
                    flush=True,
                )
                recovery_reboot = call("adb", "reboot", "bootloader", timeout=20)
                result["recovery"] = recovery_reboot.stdout
                recovery_reboot.check_returncode()
                result["verdict"] = (
                    "Recovery entered; device returned to bootloader without wiping data."
                )
                break
            if state == "fastboot":
                result["verdict"] = (
                    "Device returned to fastboot before Android completed."
                )
                break
            # Give fastboot boot time to hand control to the kernel before
            # treating a fastboot device as a failed reboot.
            if time.monotonic() - boot_started >= 10:
                fastboot = subprocess.run(
                    ["fastboot", "devices"],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=15,
                )
                if args.serial in fastboot.stdout:
                    result["fastboot_return"] = fastboot.stdout
                    result["verdict"] = (
                        "Device returned to fastboot before Android completed."
                    )
                    break
            sample = call(
                "adb",
                "shell",
                "uname -r; getprop sys.boot_completed; getprop ro.boot.bootreason",
            )
            if sample.returncode == 0:
                values = sample.stdout.strip().splitlines()
                if len(values) >= 3:
                    kernel, completed, reason = (v.strip() for v in values[:3])
                    record = {
                        "kernel": kernel,
                        "boot_completed": completed,
                        "reason": reason,
                    }
                    if record != last:
                        result["samples"].append(record)
                        print(f"Device status: {record}.", flush=True)
                        last = record
                    if completed == "1":
                        result["passed"] = (
                            kernel == args.expected_kernel and "watchdog" not in reason
                        )
                        result["verdict"] = (
                            "Android completed on the requested kernel."
                            if result["passed"]
                            else "Device returned on another kernel or after watchdog."
                        )
                        break
            time.sleep(3)
        else:
            result["verdict"] = "Android did not complete before the timeout."
    except (RuntimeError, subprocess.SubprocessError) as error:
        result["verdict"] = f"Test failed: {error}"
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(result["verdict"], flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
