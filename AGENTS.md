# Agent instructions

## Working approach

- Complete authorized work autonomously, including investigation, implementation
  and verification. Ask when missing information materially changes the outcome
  and cannot be resolved from the repository or available sources.
- Inspect relevant code and local changes first. Preserve unrelated user work.
- Search the internet as needed: documentation, upstream source, issues, forums
  and Stack Overflow. Prefer primary sources; verify advice against the pinned
  dependencies and local implementation before applying it.
- Prefer supported configuration or applicable upstream fixes, then the smallest
  justified local change. Investigate failures before adding workarounds.
- Communicate in the user's language. Keep repository documentation in English.

## Verification

- ADB and fastboot are available on the host. Use `$redfin-device` for redfin
  temporary boot, reboots, screen access and SukiSU/SUSFS device checks.
- Review the final diff and run checks appropriate to the change. Fix failures
  caused by the work; report any checks that could not be completed.
- For documentation, check accuracy, links and command syntax. For code, run
  relevant style checks and tests. Kernel/config changes require patch-stack
  validation, build, temporary boot, root and affected-feature checks; preserve
  a recovery path and restore the installed kernel after testing.
- Distinguish observed results from assumptions. Report what changed, how it was
  verified and any remaining limitations.

## Reusable knowledge

After each completed task or significant milestone, update the relevant file
in `docs/` with what led to success: the cause or constraint, the effective
solution, why it works and how to verify it. Merge with existing explanations
and remove obsolete or duplicate material. Keep only reusable facts; exclude
timestamps, current-state reports, hashes, raw logs and task diaries.

Keep this file limited to stable agent rules. Read
[development procedures](docs/development.md) for build, style and device work;
read [compatibility constraints](docs/compatibility.md) when changing kernel,
SukiSU or SUSFS integration.
