#!/usr/bin/env python3
"""Launch the real Manager and verify its root server ran as UID 0."""

import argparse
import os
import subprocess
import sys

from device_test import Device, test_manager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serial", default=os.environ.get("ADB_SERIAL", "09181FDD400301")
    )
    args = parser.parse_args()
    try:
        test_manager(Device(args.serial))
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
