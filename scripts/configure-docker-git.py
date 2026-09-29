#!/usr/bin/env python3
"""Trust the pinned source mounts owned by the host, inside the build container."""

import json
import os
import pathlib
import subprocess


def configure(repo, evolution_source=None):
    records = json.loads((repo / "configs/dependencies.json").read_text())
    directories = [repo]
    for record in records:
        checkout = repo / "deps" / record["name"]
        directories.extend(
            (checkout, checkout / ".git", repo / ".git/modules" / record["name"])
        )
    if evolution_source is not None:
        directories.extend((evolution_source, evolution_source / ".git"))

    # Git 2.43 needs exact paths, including object stores used by local clones.
    # HOME=/tmp is writable in the otherwise read-only build container.
    for directory in directories:
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", str(directory)],
            check=True,
        )


if __name__ == "__main__":
    repo = pathlib.Path(__file__).resolve().parents[1]
    evolution_source = None
    if os.environ.get("BUILD_TARGET", "stock") == "evolution":
        evolution_source = pathlib.Path(
            os.environ.get("EVOLUTION_KERNEL_SOURCE", "/evolution-kernel")
        ).resolve()
    configure(repo, evolution_source)
