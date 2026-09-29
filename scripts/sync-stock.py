#!/usr/bin/env python3
"""Stage pinned, local submodules into an isolated writable build tree."""

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
DEPENDENCIES_FILE = REPO / "configs/dependencies.json"
GIT_ENV = dict(
    os.environ, GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="file"
)


def run(*args):
    """Run a local Git command without network fallback or optional writes."""
    return subprocess.check_output(args, text=True, env=GIT_ENV).strip()


def repository(name):
    """Return the canonical submodule object store, falling back to its checkout."""
    git_dir = REPO / ".git" / "modules" / name
    if git_dir.is_dir():
        return git_dir

    checkout = REPO / "deps" / name
    if (checkout / ".git").exists():
        return checkout
    raise ValueError(f"Dependency is not initialized: {name}")


def git_command(source, *args):
    """Build a Git command for either a worktree or a submodule object store."""
    if source.is_relative_to(REPO / ".git" / "modules"):
        return ("git", f"--git-dir={source}", *args)
    return ("git", "-C", str(source), *args)


def submodules():
    """Read path and URL pairs from the repository's declared git submodules."""
    output = run(
        "git",
        "-C",
        str(REPO),
        "config",
        "-f",
        ".gitmodules",
        "--get-regexp",
        r"^submodule\..*\.(path|url)$",
    )
    modules = {}
    for line in output.splitlines():
        key, value = line.split(maxsplit=1)
        match = re.fullmatch(r"submodule\.([^.]+)\.(path|url)", key)
        if not match:
            raise ValueError(f"Invalid .gitmodules entry: {key}")
        name, field = match.groups()
        if field in modules.setdefault(name, {}):
            raise ValueError(f"Duplicate .gitmodules field: {key}")
        modules[name][field] = value
    return modules


def validate(records):
    """Check manifest, gitlinks, module URLs, and pinned local object stores."""
    modules = submodules()
    names, paths = set(), set()
    for record in records:
        try:
            name, path, revision, url = (
                record[key] for key in ("name", "path", "revision", "repository")
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"Incomplete dependency record: {record}") from error

        if (
            not isinstance(name, str)
            or not isinstance(url, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name)
            or not re.fullmatch(r"[0-9a-f]{40}", revision)
            or not isinstance(path, str)
            or pathlib.PurePosixPath(path).is_absolute()
            or any(part in ("", ".", "..") for part in path.split("/"))
            or path.split("/")[0] in ("reference", "source-lock.json")
            or name in names
            or path in paths
        ):
            raise ValueError(f"Invalid or duplicate dependency: {record}")
        names.add(name)
        paths.add(path)

        module = modules.get(name)
        if module != {"path": f"deps/{name}", "url": url}:
            raise ValueError(f".gitmodules entry does not match manifest: {name}")
        source = repository(name)
        link = run("git", "-C", str(REPO), "ls-files", "--stage", "--", f"deps/{name}")
        if link.split()[:3] != ["160000", revision, "0"]:
            raise ValueError(f"Dependency gitlink mismatch: {name}")

        try:
            run(*git_command(source, "cat-file", "-e", f"{revision}^{{commit}}"))
        except subprocess.CalledProcessError as error:
            raise ValueError(f"Dependency revision is unavailable: {name}") from error

        checkout = REPO / "deps" / name
        if (checkout / ".git").exists():
            dirty = run(
                "git",
                "-C",
                str(checkout),
                "status",
                "--porcelain",
                "--untracked-files=all",
            )
            if dirty:
                print(
                    f"Dependency worktree has local changes and is excluded from "
                    f"staging: {name}.",
                    file=sys.stderr,
                    flush=True,
                )

    if names != set(modules):
        missing = sorted(set(modules) - names)
        undeclared = sorted(names - set(modules))
        raise ValueError(
            f"Submodule manifest mismatch: unused={missing}, unknown={undeclared}"
        )


def stage(record, root):
    """Clone a pinned dependency into the disposable build tree."""
    source = repository(record["name"])
    target = root / record["path"]
    if target.is_symlink():
        raise ValueError(f"Dependency destination is a symlink: {target}")
    if not target.resolve().is_relative_to(root):
        raise ValueError(f"Dependency destination escapes staging root: {target}")
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Git alternates keep the source object store read-only and avoid multi-GB copies.
    run("git", "clone", "--shared", "--no-checkout", str(source), str(target))
    sparse = {"clang": "clang-r416183b", "misc": "linux-x86"}.get(record["name"])
    if sparse:
        run("git", "-C", str(target), "sparse-checkout", "set", sparse)
    run("git", "-C", str(target), "checkout", "--detach", record["revision"])
    print(f"Staged {record['path']}: {record['revision']}.", flush=True)


def clear_stage_root(records, root):
    """Remove manifest-managed staged paths before cloning pinned dependencies."""
    root = root.resolve()
    for record in sorted(
        records, key=lambda item: item["path"].count("/"), reverse=True
    ):
        target = root / record["path"]
        if target.is_symlink():
            raise ValueError(f"Dependency destination is a symlink: {target}")
        if not target.resolve().is_relative_to(root):
            raise ValueError(f"Dependency destination escapes staging root: {target}")
        if target.exists():
            shutil.rmtree(target)
    source_lock = root / "source-lock.json"
    if source_lock.exists():
        source_lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="check pinned submodules without writing build files",
    )
    parser.add_argument(
        "--stage-root",
        type=pathlib.Path,
        default=pathlib.Path(os.environ.get("STOCK_ROOT", "/stock")),
        help="disposable writable build root (default: /stock)",
    )
    args = parser.parse_args(argv)

    try:
        records = json.loads(DEPENDENCIES_FILE.read_text())
        validate(records)
        print(f"Validated {len(records)} pinned local submodules.", flush=True)
        if args.validate_only:
            return 0

        root = args.stage_root.resolve()
        if root.is_relative_to(REPO) or REPO.is_relative_to(root):
            raise ValueError(
                f"Staging root must be isolated from the repository: {root}"
            )
        root.mkdir(parents=True, exist_ok=True)
        clear_stage_root(records, root)
        # Parent repositories must be staged before nested kernel submodules.
        for record in sorted(records, key=lambda item: item["path"].count("/")):
            stage(record, root)
        (root / "source-lock.json").write_text(json.dumps(records, indent=2) + "\n")
        print("Pinned source staging completed.", flush=True)
        return 0
    except (
        OSError,
        subprocess.CalledProcessError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(f"Dependency staging failed: {error}.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
