#!/usr/bin/env python3
"""Check project scripts, configs, patch additions and workflow shell blocks."""

import argparse
import re
import shutil
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLE_TYPES = ",".join(
    (
        "TRAILING_WHITESPACE",
        "CODE_INDENT",
        "LEADING_SPACE",
        "OPEN_BRACE",
        "POINTER_LOCATION",
        "SPACE_BEFORE_TAB",
        "INITIALISED_STATIC",
    )
)
LOG_MESSAGE = re.compile(
    r'\b(?:pr_(?:err|warn|info|debug|notice|alert|crit|emerg)|SUSFS_LOG[IE])\("[a-z]'
)


def check_workflows() -> list[str]:
    failures = []
    for workflow in sorted((ROOT / ".github/workflows").glob("*.yml")):
        lines = workflow.read_text().splitlines(keepends=True)
        for start, line in enumerate(lines):
            header = re.fullmatch(r"( +)run: \|\s*", line)
            if not header:
                continue
            indent = len(header[1])
            end = start + 1
            while end < len(lines):
                following = lines[end]
                if (
                    following.strip()
                    and len(following) - len(following.lstrip()) <= indent
                ):
                    break
                end += 1
            code = "".join(
                line[indent + 2 :] if line.strip() else "\n"
                for line in lines[start + 1 : end]
            )
            formatted = subprocess.run(
                ["shfmt", "-i", "2", "-ci", "-sr"],
                input=code,
                capture_output=True,
                text=True,
            )
            if formatted.returncode:
                failures.append(f"Invalid workflow shell: {workflow.name}:{start + 1}")
            elif formatted.stdout.rstrip() != code.rstrip():
                failures.append(
                    f"Unformatted workflow shell: {workflow.name}:{start + 1}"
                )
    return failures


def check_patches() -> int:
    failures = check_workflows()
    patches = sorted((ROOT / "patches").glob("*.patch"))
    for patch in patches:
        syntax = subprocess.run(
            ["git", "apply", "--numstat", str(patch)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if syntax.returncode or not syntax.stdout:
            failures.append(f"Invalid or empty patch: {patch.name}")
        target = ""
        for number, line in enumerate(patch.read_text().splitlines(), 1):
            if line.startswith("+++ b/"):
                target = line[6:]
            elif line.startswith("+") and not line.startswith("+++"):
                code = line[1:]
                if code.rstrip() != code:
                    failures.append(f"Trailing whitespace: {patch.name}:{number}")
                if target.endswith((".c", ".h")) and LOG_MESSAGE.search(code):
                    failures.append(f"Lowercase log message: {patch.name}:{number}")
        check = subprocess.run(
            [
                "perl",
                str(ROOT / "deps/kernel/scripts/checkpatch.pl"),
                "--no-tree",
                "--terse",
                "--types",
                STYLE_TYPES,
                str(patch),
            ],
            capture_output=True,
            text=True,
        )
        if check.returncode:
            failures.append(check.stdout + check.stderr)
    for failure in failures:
        print(failure)
    if failures:
        return 1
    print(f"Patch style passed: {len(patches)} patches.")
    return 0


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    for tool in ("shellcheck", "shfmt", "black", "gofmt", "perl", "git", "bash"):
        if not shutil.which(tool):
            print(f"Missing style tool: {tool}.", file=sys.stderr)
            return 2
    shell_files = sorted(
        [
            *ROOT.glob("scripts/*.sh"),
            ROOT / "configs/anykernel.sh",
            *ROOT.glob("configs/build.config.*"),
            *ROOT.glob("configs/*.env"),
        ]
    )
    commands = [
        ["shellcheck", "-S", "style", *map(str, shell_files)],
        ["shfmt", "-i", "2", "-ci", "-sr", "-d", *map(str, shell_files)],
        *(["bash", "-n", str(path)] for path in shell_files),
        ["black", "--check", *map(str, sorted(ROOT.glob("scripts/*.py")))],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            return result.returncode
    go = subprocess.run(
        ["gofmt", "-l", *map(str, sorted(ROOT.glob("scripts/*.go")))],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if go.returncode or go.stdout:
        print(f"Go style check failed:\n{go.stdout}{go.stderr}", file=sys.stderr)
        return 1
    if check_patches():
        return 1
    if subprocess.run(["git", "diff", "--check"], cwd=ROOT).returncode:
        return 1
    print("Project style passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
