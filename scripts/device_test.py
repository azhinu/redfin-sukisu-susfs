"""Host helpers for redfin device tests; importing this module never touches ADB."""

import hashlib
import re
import subprocess
import time
from pathlib import Path


class Device:
    def __init__(self, serial):
        self.serial = serial

    def call(self, *args, check=True, timeout=30):
        result = subprocess.run(
            ["adb", "-s", self.serial, *map(str, args)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and result.returncode:
            raise RuntimeError(
                f"ADB command failed: {' '.join(map(str, args))}: {result.stderr.strip()}"
            )
        return result

    def shell(self, command, check=True):
        return self.call("shell", command, check=check).stdout.strip()

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.call("get-state", check=False)
            if state.returncode == 0 and state.stdout.strip() == "device":
                return
            time.sleep(2)
        raise RuntimeError(f"ADB did not reconnect within {timeout} seconds.")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_manager_log(log):
    if "com.sukisu.ultra:root:0: System.exit called, status: 0" not in log:
        raise RuntimeError("Manager root server did not start and exit successfully.")
    if not re.search(r"PhantomProcessRecord .*com\.sukisu\.ultra:root:0/0\}", log):
        raise RuntimeError("Android did not report the Manager root server as UID 0.")
    if re.search(
        r"ksud::cli: Error: /data/adb/|KsuCli.*Permission denied|Writable dex file", log
    ):
        raise RuntimeError("Manager root path failed.")


def test_manager(device):
    device.call("shell", "am", "force-stop", "com.sukisu.ultra")
    device.call("logcat", "-c")
    device.call("shell", "monkey", "-p", "com.sukisu.ultra", "1")
    time.sleep(8)
    log = device.call("logcat", "-d", "-b", "all").stdout
    pattern = re.compile(
        r"KernelSU: allow root|RootServerMain|com.sukisu.ultra:root:0: System.exit called, status: 0|"
        r"ksud::cli: (command: (Install|Susfs)|Error:)|KsuCli.*Permission denied|Writable dex file"
    )
    lines = [line for line in log.splitlines() if pattern.search(line)]
    print("\n".join(lines[-30:]), flush=True)
    check_manager_log(log)
    print("Manager root server UID 0 and successful exit confirmed.", flush=True)
    if "Susfs { command: Status }" in log and "Susfs { command: Version }" in log:
        print(
            "SUSFS status/version queries observed; responses require a direct probe.",
            flush=True,
        )
    else:
        print(
            "SUSFS queries were not observed; direct status/version probes are required.",
            flush=True,
        )
    return log
