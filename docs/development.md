# Development

Pixel 5 (`redfin`) is the only device target. Stock and Evolution use separate
Linux 4.19 trees. Production integration uses built-in SukiSU, manual hooks,
and disabled KPROBES/KPM.

## Sources and pipeline

- Submodule links and `configs/dependencies.json` define dependency revisions
  and Android tree mappings; update them together.
- `configs/evolution-*.env` define Evolution kernel/ROM inputs.
  `prepare-stock-reference.sh` defines stock factory inputs.
- `sync-stock.py` stages pinned object stores into disposable clones and
  excludes local submodule edits. Complete kernel checkouts require a
  case-sensitive filesystem.
- `apply-sukisu-susfs.py` owns patch plans, source checks and integration locks.
  Each patch requires a forward apply check, or a reverse check if already
  applied. Modify staged sources through reproducible patches.
- `build-redfin-sukisu.sh` stages, patches, compiles and packages.
  `package-images.sh`, `repack-boot-v3.py` and `extract-ota-images.py` handle
  packaging and binary images; `configs/anykernel.sh` configures AnyKernel.

## Storage

| Container path | Purpose |
| --- | --- |
| `/workspace`, `/evolution-kernel` | Read-only repository and external source. |
| `/workspace/artifacts` | Writable host outputs. |
| `/stock` | Disposable clones and reference inputs in `stock-work`. |
| `/stock-out` | Objects and intermediates in `stock-build-output`. |
| `/tmp` | Temporary files and container Git configuration. |

`configure-docker-git.py` trusts exact pinned checkout/object-store paths in
container-only Git config (`HOME=/tmp`), including source `.git` paths used by
shared clones. Broad `safe.directory` wildcards are unnecessary.

`artifacts/` and local ROM inputs are excluded from Git. Outputs and volumes
may hold unique diagnostics or rollback data; inspect their consumers before
removal.

## Commands

From the repository root, with Python 3.10+ and Docker Compose:

```sh
python3 scripts/sync-stock.py --validate-only
./scripts/build-susfs.sh
./scripts/build-evolution.sh
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/check-style.py
```

The launchers select stock and Evolution SUSFS respectively. Evolution requires
its configured OTA under `rom/evolution/` and a matching kernel checkout at
`rom/evolution/kernel/` or `EVOLUTION_KERNEL_SOURCE`. `EVOLUTION_STAGE` selects
`plain`, `sukisu-minimal`, `sukisu`, or `susfs`; plain/minimal isolate failures.
`JOBS` controls parallelism; `SKIP_MRPROPER=0` selects a clean build.
`PACKAGE_ARTIFACT_DIR` is a container path under `/workspace/artifacts/`.

Host validation, patch processing and device gates use Python; shell handles
build/CI orchestration and AnyKernel/AOSP contracts. CLI names use kebab-case;
imported modules and unit tests use snake_case. `device_test.py` has no device
side effects on import. The Go app UID probe runs on the phone.

## Style

Use `.editorconfig`, `.clang-format` and `.gitattributes`. C additions follow
Linux kernel style with clang-format 18.1.8. Shell uses shfmt 3.10.0
(`-i 2 -ci -sr`) and ShellCheck; Python uses Black 26.5.1; Go uses gofmt.
Build scripts/configs use Bash; AnyKernel uses sourced POSIX sh. Log and error
messages start with a capital letter; machine protocol fields retain their
required spelling.

The checker requires ShellCheck, shfmt, Black, Go, Python, Perl, Git and Bash.
Format C patch additions on disposable trees, regenerate later patch context,
update postimage checks,
and verify all affected plans with `git apply --check`. Preserve upstream
submodules and unchanged diff context. Full checkpatch diagnostics require
review before changing APIs.

## Device validation

ADB and fastboot are installed at `/usr/local/bin/adb` and
`/usr/local/bin/fastboot` and are available through PATH. Discover the connected
serial with `adb devices -l` / `fastboot devices`; pass it explicitly to every
operation. Sandbox USB/listener errors require host permission, not a kernel
change. Device presence and root state must be checked each time.

The personal `$redfin-device` skill contains device access, temporary boot,
reboot and recovery procedures. Reusing the existing Python gates separates
boot completion, Manager rootserver, ADB Root and observable SUSFS effects;
screen access and bootloader unlock remain distinct operations.

The Evolution gate requires ADB, fastboot, Go, an unlocked bootloader and the
matching ROM. Supply the serial, artifact directory and installed release:

```sh
EXPECTED_INSTALLED_KERNEL="$INSTALLED_KERNEL_RELEASE" \
  python3 scripts/test-connected-redfin.py --skip-build \
  --serial "$ADB_SERIAL" --artifacts "$TEST_ARTIFACT_DIR"
```

The gate checks artifact integrity, temporary boot, Manager rootserver UID 0,
ADB Root, repeated PTY wrapper close, and UNAME/OPEN_REDIRECT/SUS_PATH/KSTAT
operations. SUS_PATH/KSTAT use app UID probes with root controls. It returns to
the installed kernel without flashing partitions. Host tests cover
orchestration; they do not establish kernel behavior.

ADB Root may require a manual off/on toggle in Manager after temporary boot.
If shell remains UID 2000 after enabling it, run `adb -s "$ADB_SERIAL" root`
to restart adbd, then verify UID 0 and `u:r:ksu:s0` with `shell id`.
`--resume` requires `TEST_BOOT_REPORT` for the same image, kernel release and
current boot ID. Building through the gate requires an output path inside
repository `artifacts/`; `--skip-build` allows external artifacts. Checksum
entries cannot escape that directory.

The Manager smoke test clears logcat; preserve diagnostics first. Cleanup flags
precede mutations because an ADB timeout can follow kernel acceptance. Cleanup
restores UNAME, removes probe files and reboots to discard stateful rules.
Integration constraints are in [compatibility.md](compatibility.md).

## Documentation maintenance

Separating stable agent rules in `AGENTS.md`, development procedures here and
adapter rationale in `compatibility.md` removes repeated context. Configuration
and scripts remain authoritative for pins, paths and commands. Check local
links and command syntax after consolidation; replace obsolete references
instead of retaining compatibility stubs.
