#!/usr/bin/env python3
"""Detect Pixel recovery ADB and move it to bootloader without wiping data."""

import argparse
import subprocess
import time


def adb_devices():
    result = subprocess.run(
        ["adb", "devices", "-l"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
    )
    for line in result.stdout.splitlines():
        fields = line.split()
        if fields and fields[0] != "List" and len(fields) >= 2:
            yield fields[0], fields[1], line


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    last = None
    while time.monotonic() < deadline:
        try:
            devices = list(adb_devices())
        except subprocess.SubprocessError as error:
            print(f"ADB probe failed: {error}.", flush=True)
            devices = []
        matching = next(
            (state for serial, state, _ in devices if serial == args.serial), None
        )
        if matching != last:
            print(f'Device state: {matching or "absent"}.', flush=True)
            last = matching
        if matching == "recovery":
            print(
                "Recovery detected; rebooting to bootloader without wiping data.",
                flush=True,
            )
            result = subprocess.run(
                ["adb", "-s", args.serial, "reboot", "bootloader"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=20,
            )
            print(result.stdout, end="", flush=True)
            result.check_returncode()
            return 0
        if matching == "device":
            print("Android is running; recovery was not entered.", flush=True)
            return 0
        time.sleep(2)
    print("Recovery was not detected before timeout.", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
