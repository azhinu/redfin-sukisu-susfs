# Compatibility

## Integration boundary

Pinned SukiSU v4.2.0 has no SUSFS Kconfig/Makefile integration. External SUSFS
`kernel-4.19` targets original KernelSU's legacy layout; its companion patch is
incompatible with SukiSU's modular layout. The repository supplies local
Kconfig, initialization, task-state, SELinux and userspace ABI adapters.
`ENABLE_SUSFS=1` selects them. Revisions and patch order live in configuration,
submodule links and `scripts/apply-sukisu-susfs.py`.

Sources: [SukiSU Kconfig](../deps/sukisu/kernel/Kconfig),
[SukiSU integration guide](../deps/sukisu/docs/guide/how-to-integrate.md),
[SUSFS README](../deps/susfs/README.md),
[SUSFS companion patch](../deps/susfs/kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch).
Selecting another driver revision requires a new source/API comparison.

## Driver constraints

| Area | Constraint |
| --- | --- |
| Manual hooks | Keep early exec bootstrap active for `on_post_fs_data()`, plus reboot/setresuid driver handoff. |
| Manager identity | Use package/certificate tracking; a numeric UID fallback bypasses authentication. |
| ADB Root | Manual exec setup must release the filename and propagate negative `setup_ld_preload` results. |
| Classic `su` | Unavailable in production manual-hook mode: the syscall bridge is disabled and `su_compat` is unregistered. Manager rootserver/ADB Root use separate paths. |
| SELinux policy | Allocate before publication, serialize reload, preserve live policy on failure; sleeping work cannot run under a spinlock. OOM/malformed-policy rollback needs separate coverage. |
| SELinux hide | Feature object and handler are excluded. |
| Kernel APIs | Namespace, task, nofault, fsnotify and header adapters match older APIs; `sucompat-pgtable` is stock-only. |
| Clocksource spoofing | Absent-field compile guard does not establish full spoofing behavior. |
| Reported status | Driver code, SUSFS version/status and feature bits do not prove UAPI compatibility or operations. The preserved upstream hook-type text reports tracepoint redirect even in manual mode. |

### Seccomp

ARM64 `reboot` is syscall 142. `SIGSYS`/`SYS_SECCOMP` rejects it before the
manual handler runs. SukiSU uses reboot transport for driver FD installation.
Linux 4.19 lacks the allow-cache API; its cache shim is compile-only.

The `seccomp-disable-old` adapter calls `ksu_disable_seccomp()` before FD
installation for the authenticated Manager and allowlisted UIDs. Companion
adapters handle the cache shim, absent filter-count field and older release
API. The fallback follows
[SukiSU PR #545](https://github.com/SukiSU-Ultra/SukiSU-Ultra/pull/545).
Validate driver discovery and trusted-UID filter handling independently of boot.

### File wrapper

Evolution stores SELinux inode security at an offset inside a shared LSM blob.
Raw `i_security` access corrupts fields and can produce `list_del corruption`
in `selinux_inode_free_security` during PTY/wrapper close.

The [Evolution overlay](../patches/sukisu-v4.2.0-evolution-4.19-file-wrapper-lsm-blob.patch)
replaces three accesses with `selinux_inode()`: anon inode, context inode and
wrapper inode. Stock allocates SELinux inode security directly and lacks the
helper. Keep this selection target-specific; validate descriptor close, kernel
liveness and fault logs through the device gate.

## SUSFS invariants

| Overlay suffix | Required behavior |
| --- | --- |
| `pathname-validation` | Validate NUL termination before string operations and terminate copied kernel strings. |
| `concurrency` | Serialize writers, protect readers with RCU, publish replacements before retirement and free after `synchronize_rcu()`. |
| `callsite-safety` | Release path/mount references and handle `ERR_PTR` results. |
| `correctness` | Preserve inode identity across cache reload and remove rules before inode reuse/unmount. |
| `kstat-forward-declaration` | Declare `struct kstat` at file scope without weakening Clang diagnostics. |

Files use `susfs-1.5.5-` under `patches/`. KSTAT path lookup/allocation runs
outside spinlock/RCU sections; readers copy scalars under RCU. OPEN_REDIRECT
copies its pathname under RCU before `getname_kernel()`. SUS_MOUNT balances
path references under mutex protection; CMDLINE publication/readers share a
mutex, and UNAME readers/writers share a lock.

Rule identity is `(monotonic superblock ID, inode number)`; mutable
`i_generation` is unsuitable. Eviction removes unlinked-inode rules before
inode reuse; superblock shutdown removes remaining rules. `unlock_new_inode()`
restores markers for linked inodes. KSTAT runs after base stat fields are
filled. Inotify fdinfo suppresses real file handles while spoofing. Enabling
FANOTIFY requires equivalent fdinfo review.

Stock applies upstream SUSFS callsites plus a style overlay. Evolution uses a
combined fs-context/mount adaptation before the shared repairs.

The reboot and legacy prctl transports coexist. Reboot dispatch is root-gated;
unsupported commands return `126`. OPEN_REDIRECT accepts UID scheme `2` because
the table has no per-UID field. SUS map, `ADD_SUS_PATH_LOOP`, reboot-ABI
hide-mounts and AVC spoofing are unsupported. TRY_UMOUNT/auto-mount helpers stay
disabled. Retained `sukisu-40922-*` filenames describe legacy adapter provenance,
not the configured driver code.

## Memcg diagnostics

`mem_cgroup_update_lru_size` warns on a negative per-cgroup LRU count along the
`release_pages -> free_pages_and_swap_cache -> exit_mmap` path. Without
`CONFIG_DEBUG_VM`, the source resets the count after warning; `WARN_ONCE` masks
recurrence frequency.

The warning also occurs without SukiSU/SUSFS. The patch stack does not modify
`mm/memcontrol.c`; compiler differences remain an unproven hypothesis.
Investigate with matching sources/configuration/compiler and process-exit
workload before changing accounting. Preserve the warning and diagnostics.
