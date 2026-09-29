# Patch stack

`scripts/apply-sukisu-susfs.py` applies this stack to disposable copies under
`/stock`; it never patches the dependency submodules in place. It checks each
patch with `git apply --check`, accepts an already-applied patch only when the
reverse check succeeds, and writes the exact dependency and patch pins to
`sukisu-susfs.lock`.

The default pinned SukiSU v4.2.0 path (`85eb4a95…`) remains opt-in for SUSFS:
`ENABLE_SUSFS=0` records `SUSFS=not-integrated`. The verified SUSFS build uses
`ENABLE_SUSFS=1` and records `INTEGRATION_MODE=sukisu-v4.2.0-susfs-dual-abi`.
The source and helper revisions are never substituted by compatibility patches.

The order matters:

1. `deps/susfs/kernel_patches/50_add_susfs_in_kernel-4.19.patch` installs
   SUSFS call sites; the pinned SUSFS C source and headers are copied alongside
   it and verified by SHA256.
   Stock then applies `susfs-1.5.5-stock-callsite-style.patch` so its callsites
   use the same C style and overlay context as the Evolution combined patch.
   This patch changes whitespace only; its SHA is recorded in the stock lock.
2. `susfs-1.5.5-pathname-validation.patch`,
   `susfs-1.5.5-concurrency.patch`, `susfs-1.5.5-callsite-safety.patch`, and
   `susfs-1.5.5-correctness.patch` repair the pinned SUSFS code. They validate
   user pathname inputs, protect shared state and references, close unsafe
   call-site paths, and preserve inode identity and rule lifecycle in Linux 4.19.
   `susfs-1.5.5-kstat-forward-declaration.patch` adds the missing file-scope
   declaration required by the pinned kernel's strict Clang build.
3. `redbull-kernelsu-integration.patch` adds the built-in Kconfig and Makefile
   entries. `redbull-kernelsu-manual-hooks.patch` and
   `redbull-kernelsu-setresuid-hook.patch` add the MANUAL_HOOK and Manager
   handoff call sites required by this non-GKI target.
   Evolution uses the upstream APK signature and package tracker for Manager
   discovery; the rejected numeric UID fallback has been removed.
   The early exec hook stays active so `on_post_fs_data()` runs when zygote
   starts. The SELinux policy patch serializes updates and loads the completed
   policy through `security_load_policy` on Linux 4.19.
   `sukisu-v4.2.0-redbull-4.19-selinux-hide-disabled.patch` removes the
   unverified SELinux hide feature from this target's built-in driver. Its
   feature handler is absent, so userspace cannot enable it.
   `sukisu-v4.2.0-redbull-4.19-manual-adb-root.patch` and its callsite patch
   connect the ADB Root feature to the manual `execve` path for `adbd`.
   Classic `su` stays unsupported in manual-hook mode: the syscall bridge
   that handles its `execve`/`stat`/`faccessat` path is disabled, so the
   `su_compat` feature handler is not registered. A Manager root server and
   ADB Root do not require that feature.
4. `susfs-v1.5.5-reboot-abi.patch` adds the SukiSU v4.2 reboot ABI dispatcher;
   `susfs-v1.5.5-reboot-abi-hook.patch` includes it in the pinned SUSFS source.
5. `sukisu-v4.2.0-susfs-kernel.patch` and
   `sukisu-v4.2.0-redbull-4.19-susfs-reboot-callsite.patch` connect that
   dispatcher to SukiSU and the manual reboot syscall call site.
6. `sukisu-v4.2.0-susfs-prctl-handler.patch` plus
   `sukisu-v4.2.0-redbull-4.19-susfs-prctl-callsite.patch` preserve the legacy
   helper's prctl ABI. The installed `susfs4ksu` v1.5.2-R28 helper on the
   tested device selected `sys_reboot`; the prctl path remains for legacy
   helpers that use it.

For `BUILD_TARGET=evolution`, the pinned Evolution `4.19.325` tree has newer
`fs_context` and mount allocation signatures than the stock `4.19.278` tree.
`susfs-1.5.5-evolution-4.19.325-combined.patch` applies the upstream call
sites plus the three reviewed Evolution adaptations as one patch after
`git apply --check`. Stock builds retain the pinned upstream patch followed
by the local callsite formatting patch.
The common SukiSU 4.19 file-wrapper adapter uses the direct SELinux inode
security pointer of stock redbull. Evolution stores SELinux data at an offset
inside the shared LSM blob, so
`sukisu-v4.2.0-evolution-4.19-file-wrapper-lsm-blob.patch` replaces its three
raw pointer reads with `selinux_inode()` after the common adapter. The
Evolution lock records the overlay SHA256. See the
[compatibility notes](../docs/compatibility.md) before testing its
wrapper FD path on a device.

The reboot path is root-gated. `ADD_SUS_PATH_LOOP`, hide-mounts, AVC spoofing,
and SUS map are reported as ABI sentinel `126`; OPEN_REDIRECT is accepted only
for UID scheme `2`, because the pinned 1.5.5 table has no per-UID field.

The KernelSU patches cover `exec`, `faccessat`, `read`, `stat`, `reboot`, and
`setresuid`. SUSFS support is limited to operations implemented by the adapter
and enabled in `configs/build.config.redbull.sukisu`; presence of a command
number or a reported SUSFS version does not prove that every operation works.
The adapter is a project-specific compatibility layer, not a general upstream
backport.

See [compatibility notes](../docs/compatibility.md) for source links,
adapter constraints and runtime validation requirements.
