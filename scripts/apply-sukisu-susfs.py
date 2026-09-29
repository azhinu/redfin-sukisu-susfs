#!/usr/bin/env python3
"""Apply the pinned SukiSU/SUSFS patch stack to disposable build sources.

The environment and lock format match the build pipeline. No shell code is
executed here; every git patch is checked before application.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

SUKISU_REF = "85eb4a95b8a61d756ecf53b9c5785e48e1b15039"
SUSFS_REF = "001e69919c6271f690fd00b17e4c721c9e599152"
SOURCE_HASHES = {
    "fs/susfs.c": "cd117f5a7900048fdf2abf87d70ef65c01c634b2ff6ccf8fe079fbd6766d7251",
    "include/linux/susfs.h": "fb0b83e9f4188d8887e8a63554bf8c551cdf7544924da93e973f7d2ea19451b8",
    "include/linux/susfs_def.h": "b40f4018de7aa9c5b93b2973b9e4ed2eaaeb0bacbe02e4df8376eac13d309bf3",
}

# Local name -> environment override and default filename.
PATCHES = {
    "kernel_integration_patch": (
        "KERNEL_API_PATCH_FILE",
        "redbull-kernelsu-integration.patch",
    ),
    "kernel_namespace_helpers_patch": (
        "KERNEL_NAMESPACE_HELPERS_PATCH_FILE",
        "redbull-kernel-4.19-namespace-helpers.patch",
    ),
    "kernel_setns_helper_patch": (
        "KERNEL_SETNS_HELPER_PATCH_FILE",
        "redbull-kernel-4.19-setns-helper.patch",
    ),
    "sukisu_v420_manual_hooks_patch": (
        "SUKISU_V420_MANUAL_HOOKS_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-manual-hooks.patch",
    ),
    "sukisu_v420_manual_exec_runtime_patch": (
        "SUKISU_V420_MANUAL_EXEC_RUNTIME_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-manual-exec-runtime.patch",
    ),
    "sukisu_v420_manual_bootstrap_patch": (
        "SUKISU_V420_MANUAL_BOOTSTRAP_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-manual-bootstrap.patch",
    ),
    "sukisu_v420_manual_adb_root_patch": (
        "SUKISU_V420_MANUAL_ADB_ROOT_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-manual-adb-root.patch",
    ),
    "sukisu_v420_manual_adb_root_callsite_patch": (
        "SUKISU_V420_MANUAL_ADB_ROOT_CALLSITE_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-manual-adb-root-callsite.patch",
    ),
    "sukisu_v420_manual_exec_callsite_patch": (
        "SUKISU_V420_MANUAL_EXEC_CALLSITE_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-manual-exec-callsite.patch",
    ),
    "sukisu_v420_manual_setresuid_patch": (
        "SUKISU_V420_MANUAL_SETRESUID_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-manual-setresuid.patch",
    ),
    "sukisu_v420_manual_supercall_patch": (
        "SUKISU_V420_MANUAL_SUPERCALL_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-manual-supercall.patch",
    ),
    "sukisu_v420_manual_reboot_handler_patch": (
        "SUKISU_V420_MANUAL_REBOOT_HANDLER_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-manual-reboot-handler.patch",
    ),
    "sukisu_v420_manual_reboot_callsite_patch": (
        "SUKISU_V420_MANUAL_REBOOT_CALLSITE_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-manual-reboot-callsite.patch",
    ),
    "sukisu_v420_manual_kprobes_off_patch": (
        "SUKISU_V420_MANUAL_KPROBES_OFF_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-manual-kprobes-off.patch",
    ),
    "sukisu_v420_redbull_compat_patch": (
        "SUKISU_V420_REDBULL_COMPAT_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-module-import-ns.patch",
    ),
    "sukisu_v420_sucompat_pgtable_patch": (
        "SUKISU_V420_SUCOMPAT_PGTABLE_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-sucompat-pgtable.patch",
    ),
    "sukisu_v420_nofault_patch": (
        "SUKISU_V420_NOFAULT_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-nofault-api.patch",
    ),
    "sukisu_v420_user_nofault_patch": (
        "SUKISU_V420_USER_NOFAULT_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-user-nofault-api.patch",
    ),
    "sukisu_v420_selinux_cred_patch": (
        "SUKISU_V420_SELINUX_CRED_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-selinux-cred.patch",
    ),
    "sukisu_v420_file_wrapper_patch": (
        "SUKISU_V420_FILE_WRAPPER_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-file-wrapper.patch",
    ),
    "sukisu_v420_evolution_file_wrapper_patch": (
        "SUKISU_V420_EVOLUTION_FILE_WRAPPER_PATCH_FILE",
        "sukisu-v4.2.0-evolution-4.19-file-wrapper-lsm-blob.patch",
    ),
    "sukisu_v420_seccomp_patch": (
        "SUKISU_V420_SECCOMP_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-seccomp-native-nr.patch",
    ),
    "sukisu_v420_seccomp_disable_old_patch": (
        "SUKISU_V420_SECCOMP_DISABLE_OLD_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-seccomp-disable-old.patch",
    ),
    "sukisu_v420_mount_header_patch": (
        "SUKISU_V420_MOUNT_HEADER_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-su-mount-header.patch",
    ),
    "sukisu_v420_fsnotify_patch": (
        "SUKISU_V420_FSNOTIFY_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-fsnotify.patch",
    ),
    "sukisu_v420_allowlist_patch": (
        "SUKISU_V420_ALLOWLIST_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-allowlist-api.patch",
    ),
    "sukisu_v420_seccomp_filter_count_patch": (
        "SUKISU_V420_SECCOMP_FILTER_COUNT_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-seccomp-filter-count.patch",
    ),
    "sukisu_v420_seccomp_release_patch": (
        "SUKISU_V420_SECCOMP_RELEASE_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-seccomp-release.patch",
    ),
    "sukisu_v420_selinux_policy_patch": (
        "SUKISU_V420_SELINUX_POLICY_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-selinux-policy.patch",
    ),
    "sukisu_v420_selinux_sepolicy_api_patch": (
        "SUKISU_V420_SELINUX_SEPOLICY_API_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-selinux-sepolicy-api.patch",
    ),
    "sukisu_v420_minmax_header_patch": (
        "SUKISU_V420_MINMAX_HEADER_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-minmax-header.patch",
    ),
    "sukisu_v420_tasklist_api_patch": (
        "SUKISU_V420_TASKLIST_API_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-tasklist-api.patch",
    ),
    "sukisu_v420_task_work_notify_patch": (
        "SUKISU_V420_TASK_WORK_NOTIFY_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-task-work-notify.patch",
    ),
    "sukisu_v420_selinux_hide_disabled_patch": (
        "SUKISU_V420_SELINUX_HIDE_DISABLED_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-selinux-hide-disabled.patch",
    ),
    "sukisu_v420_cpu_spoof_clocksource_patch": (
        "SUKISU_V420_CPU_SPOOF_CLOCKSOURCE_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-cpu-spoof-clocksource.patch",
    ),
    "sukisu_v420_susfs_kernel_patch": (
        "SUKISU_V420_SUSFS_KERNEL_PATCH_FILE",
        "sukisu-v4.2.0-susfs-kernel.patch",
    ),
    "sukisu_v420_susfs_prctl_handler_patch": (
        "SUKISU_V420_SUSFS_PRCTL_HANDLER_PATCH_FILE",
        "sukisu-v4.2.0-susfs-prctl-handler.patch",
    ),
    "sukisu_v420_susfs_reboot_callsite_patch": (
        "SUKISU_V420_SUSFS_REBOOT_CALLSITE_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-susfs-reboot-callsite.patch",
    ),
    "sukisu_v420_susfs_prctl_callsite_patch": (
        "SUKISU_V420_SUSFS_PRCTL_CALLSITE_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-susfs-prctl-callsite.patch",
    ),
    "sukisu_v420_namespace_api_patch": (
        "SUKISU_V420_NAMESPACE_API_PATCH_FILE",
        "sukisu-v4.2.0-redbull-4.19-namespace-api.patch",
    ),
    "sukisu_v420_driver_version_patch": (
        "SUKISU_V420_DRIVER_VERSION_PATCH_FILE",
        "sukisu-v4.2.0-driver-version-override.patch",
    ),
    "sukisu_compat_patch": (
        "SUKISU_COMPAT_PATCH_FILE",
        "sukisu-40922-susfs-v155-prctl.patch",
    ),
    "sukisu_legacy_reboot_patch": (
        "SUKISU_LEGACY_REBOOT_PATCH_FILE",
        "sukisu-40922-disable-legacy-susfs-reboot.patch",
    ),
    "sukisu_current_proc_patch": (
        "SUKISU_CURRENT_PROC_PATCH_FILE",
        "sukisu-40922-susfs-current-proc-state.patch",
    ),
    "susfs_prctl_hook_patch": (
        "SUSFS_PRCTL_HOOK_PATCH_FILE",
        "redbull-kernelsu-susfs-prctl-hook.patch",
    ),
    "susfs_path_validation_patch": (
        "SUSFS_PATH_VALIDATION_PATCH_FILE",
        "susfs-1.5.5-pathname-validation.patch",
    ),
    "susfs_concurrency_patch": (
        "SUSFS_CONCURRENCY_PATCH_FILE",
        "susfs-1.5.5-concurrency.patch",
    ),
    "susfs_callsite_safety_patch": (
        "SUSFS_CALLSITE_SAFETY_PATCH_FILE",
        "susfs-1.5.5-callsite-safety.patch",
    ),
    "susfs_correctness_patch": (
        "SUSFS_CORRECTNESS_PATCH_FILE",
        "susfs-1.5.5-correctness.patch",
    ),
    "susfs_kstat_forward_patch": (
        "SUSFS_KSTAT_FORWARD_PATCH_FILE",
        "susfs-1.5.5-kstat-forward-declaration.patch",
    ),
    "susfs_reboot_abi_patch": (
        "SUSFS_REBOOT_ABI_PATCH_FILE",
        "susfs-v1.5.5-reboot-abi.patch",
    ),
    "susfs_reboot_abi_hook_patch": (
        "SUSFS_REBOOT_ABI_HOOK_PATCH_FILE",
        "susfs-v1.5.5-reboot-abi-hook.patch",
    ),
    "susfs_evolution_combined_patch": (
        "SUSFS_EVOLUTION_COMBINED_PATCH_FILE",
        "susfs-1.5.5-evolution-4.19.325-combined.patch",
    ),
    "susfs_stock_callsite_style_patch": (
        "SUSFS_STOCK_CALLSITE_STYLE_PATCH_FILE",
        "susfs-1.5.5-stock-callsite-style.patch",
    ),
    "manual_hooks_patch": (
        "KSU_MANUAL_HOOKS_PATCH_FILE",
        "redbull-kernelsu-manual-hooks.patch",
    ),
    "setresuid_hook_patch": (
        "KSU_SETRESUID_HOOK_PATCH_FILE",
        "redbull-kernelsu-setresuid-hook.patch",
    ),
}


BASE_PLAN = (
    (
        "kernel",
        "kernel_integration_patch",
        "Redfin SukiSU v4.2.0 Kconfig integration patch",
        "all",
    ),
    (
        "kernel",
        "kernel_namespace_helpers_patch",
        "Redbull kernel 4.19 namespace helper compatibility patch",
        "all",
    ),
    (
        "kernel",
        "kernel_setns_helper_patch",
        "Redbull kernel 4.19 setns helper compatibility patch",
        "all",
    ),
    (
        "kernel",
        "sukisu_v420_manual_setresuid_patch",
        "SukiSU v4.2.0 manual setresuid callsite patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_redbull_compat_patch",
        "SukiSU v4.2.0 redbull 4.19 compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_sucompat_pgtable_patch",
        "SukiSU v4.2.0 sucompat pgtable compatibility patch",
        "stock",
    ),
    (
        "sukisu",
        "sukisu_v420_nofault_patch",
        "SukiSU v4.2.0 redbull 4.19 nofault API compatibility patch",
        "stock",
    ),
    (
        "sukisu",
        "sukisu_v420_user_nofault_patch",
        "SukiSU v4.2.0 redbull 4.19 user-nofault API compatibility patch",
        "stock",
    ),
    (
        "sukisu",
        "sukisu_v420_selinux_cred_patch",
        "SukiSU v4.2.0 redbull 4.19 SELinux cred compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_file_wrapper_patch",
        "SukiSU v4.2.0 redbull 4.19 file-wrapper compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_evolution_file_wrapper_patch",
        "SukiSU v4.2.0 Evolution 4.19 SELinux LSM blob offset patch",
        "evolution",
    ),
    (
        "sukisu",
        "sukisu_v420_seccomp_patch",
        "SukiSU v4.2.0 redbull 4.19 seccomp compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_seccomp_disable_old_patch",
        "SukiSU v4.2.0 redbull 4.19 old-kernel seccomp fallback patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_mount_header_patch",
        "SukiSU v4.2.0 redbull 4.19 mount-header compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_namespace_api_patch",
        "SukiSU v4.2.0 redbull 4.19 namespace API compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_driver_version_patch",
        "SukiSU v4.2.0 pinned Manager driver-version compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_manual_hooks_patch",
        "SukiSU v4.2.0 redbull 4.19 manual-hook compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_manual_exec_runtime_patch",
        "SukiSU v4.2.0 redbull 4.19 manual exec runtime compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_manual_bootstrap_patch",
        "SukiSU v4.2.0 redbull 4.19 deferred manual bootstrap compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_manual_adb_root_patch",
        "SukiSU v4.2.0 redbull 4.19 manual ADB Root handler",
        "all",
    ),
    (
        "kernel",
        "sukisu_v420_manual_exec_callsite_patch",
        "SukiSU v4.2.0 redbull 4.19 manual exec callsite compatibility patch",
        "all",
    ),
    (
        "kernel",
        "sukisu_v420_manual_adb_root_callsite_patch",
        "SukiSU v4.2.0 redbull 4.19 manual ADB Root exec callsite",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_manual_supercall_patch",
        "SukiSU v4.2.0 redbull 4.19 manual supercall diagnostic guard",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_manual_reboot_handler_patch",
        "SukiSU v4.2.0 redbull 4.19 manual reboot handler",
        "all",
    ),
    (
        "kernel",
        "sukisu_v420_manual_reboot_callsite_patch",
        "SukiSU v4.2.0 redbull 4.19 manual reboot callsite",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_manual_kprobes_off_patch",
        "SukiSU v4.2.0 redbull 4.19 manual Kprobes-off compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_fsnotify_patch",
        "SukiSU v4.2.0 redbull 4.19 fsnotify compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_allowlist_patch",
        "SukiSU v4.2.0 redbull 4.19 allowlist API compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_seccomp_filter_count_patch",
        "SukiSU v4.2.0 redbull 4.19 seccomp filter-count compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_seccomp_release_patch",
        "SukiSU v4.2.0 redbull 4.19 seccomp release compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_selinux_policy_patch",
        "SukiSU v4.2.0 redbull 4.19 SELinux policy compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_selinux_sepolicy_api_patch",
        "SukiSU v4.2.0 redbull 4.19 SELinux policydb API compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_minmax_header_patch",
        "SukiSU v4.2.0 redbull 4.19 minmax header compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_tasklist_api_patch",
        "SukiSU v4.2.0 redbull 4.19 tasklist API compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_task_work_notify_patch",
        "SukiSU v4.2.0 redbull 4.19 task-work notification compatibility patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_selinux_hide_disabled_patch",
        "SukiSU v4.2.0 redbull 4.19 SELinux hide disable patch",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_cpu_spoof_clocksource_patch",
        "SukiSU v4.2.0 redbull 4.19 CPU spoof clocksource compatibility patch",
        "all",
    ),
)

# The minimal isolation stage uses compile compatibility patches only.
# Filtering the base plan keeps their shared application order explicit.
MINIMAL_PATCHES = frozenset(
    (
        "kernel_integration_patch",
        "kernel_namespace_helpers_patch",
        "kernel_setns_helper_patch",
        "sukisu_v420_redbull_compat_patch",
        "sukisu_v420_selinux_cred_patch",
        "sukisu_v420_file_wrapper_patch",
        "sukisu_v420_evolution_file_wrapper_patch",
        "sukisu_v420_seccomp_patch",
        "sukisu_v420_seccomp_disable_old_patch",
        "sukisu_v420_mount_header_patch",
        "sukisu_v420_namespace_api_patch",
        "sukisu_v420_fsnotify_patch",
        "sukisu_v420_allowlist_patch",
        "sukisu_v420_seccomp_filter_count_patch",
        "sukisu_v420_seccomp_release_patch",
        "sukisu_v420_selinux_policy_patch",
        "sukisu_v420_selinux_sepolicy_api_patch",
        "sukisu_v420_minmax_header_patch",
        "sukisu_v420_tasklist_api_patch",
        "sukisu_v420_task_work_notify_patch",
        "sukisu_v420_selinux_hide_disabled_patch",
        "sukisu_v420_cpu_spoof_clocksource_patch",
    )
)
MINIMAL_PLAN = tuple(entry for entry in BASE_PLAN if entry[1] in MINIMAL_PATCHES)

SUSFS_PLAN = (
    (
        "kernel",
        "susfs_stock_callsite_style_patch",
        "SUSFS 1.5.5 stock callsite formatting",
        "stock",
    ),
    (
        "kernel",
        "susfs_path_validation_patch",
        "SUSFS 1.5.5 user pathname validation",
        "all",
    ),
    (
        "kernel",
        "susfs_concurrency_patch",
        "SUSFS 1.5.5 concurrency and lifetime fixes",
        "all",
    ),
    (
        "kernel",
        "susfs_callsite_safety_patch",
        "SUSFS 1.5.5 callsite safety fixes",
        "all",
    ),
    (
        "kernel",
        "susfs_correctness_patch",
        "SUSFS 1.5.5 inode lifecycle and spoofing correctness fixes",
        "all",
    ),
    (
        "kernel",
        "susfs_kstat_forward_patch",
        "SUSFS KSTAT struct forward declaration",
        "all",
    ),
    (
        "kernel",
        "susfs_reboot_abi_patch",
        "SUSFS 1.5.5 SukiSU v4.2 reboot ABI bridge source",
        "all",
    ),
    (
        "kernel",
        "susfs_reboot_abi_hook_patch",
        "SUSFS 1.5.5 reboot ABI bridge hook",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_susfs_kernel_patch",
        "SukiSU v4.2.0 SUSFS kernel compatibility layer",
        "all",
    ),
    (
        "sukisu",
        "sukisu_v420_susfs_prctl_handler_patch",
        "SukiSU v4.2.0 SUSFS legacy helper prctl handler",
        "all",
    ),
    (
        "kernel",
        "sukisu_v420_susfs_reboot_callsite_patch",
        "SukiSU v4.2.0 SUSFS reboot syscall callsite",
        "all",
    ),
    (
        "kernel",
        "sukisu_v420_susfs_prctl_callsite_patch",
        "SukiSU v4.2.0 SUSFS legacy helper prctl callsite",
        "all",
    ),
)

LEGACY_PLAN = (
    (
        "kernel",
        "susfs_stock_callsite_style_patch",
        "SUSFS 1.5.5 stock callsite formatting",
        "all",
    ),
    (
        "kernel",
        "susfs_path_validation_patch",
        "SUSFS 1.5.5 user pathname validation",
        "all",
    ),
    (
        "kernel",
        "susfs_concurrency_patch",
        "SUSFS 1.5.5 concurrency and lifetime fixes",
        "all",
    ),
    (
        "kernel",
        "susfs_callsite_safety_patch",
        "SUSFS 1.5.5 callsite safety fixes",
        "all",
    ),
    (
        "kernel",
        "susfs_correctness_patch",
        "SUSFS 1.5.5 inode lifecycle and spoofing correctness fixes",
        "all",
    ),
    (
        "kernel",
        "susfs_kstat_forward_patch",
        "SUSFS KSTAT struct forward declaration",
        "all",
    ),
    (
        "kernel",
        "kernel_integration_patch",
        "Redfin KernelSU Kconfig integration patch",
        "all",
    ),
    (
        "kernel",
        "manual_hooks_patch",
        "KernelSU MANUAL_HOOK call sites for redbull 4.19",
        "all",
    ),
    (
        "kernel",
        "setresuid_hook_patch",
        "KernelSU setresuid hook for Manager seccomp handoff",
        "all",
    ),
    (
        "kernel",
        "susfs_prctl_hook_patch",
        "SUSFS 1.5.5 prctl call site for redbull 4.19",
        "all",
    ),
    ("sukisu", "sukisu_compat_patch", "Pinned SukiSU SUSFS 1.5.5 prctl adapter", "all"),
    (
        "sukisu",
        "sukisu_legacy_reboot_patch",
        "Removal of incompatible SukiSU legacy SUSFS reboot ABI",
        "all",
    ),
    (
        "sukisu",
        "sukisu_current_proc_patch",
        "SukiSU SUSFS current-process state adapter",
        "all",
    ),
)


def base_lock(self):
    fields = {}
    fields["SUKISU_REPO"] = "https://github.com/SukiSU-Ultra/SukiSU-Ultra.git"
    fields["SUKISU_REF"] = self.sukisu_ref
    fields["SUKISU_DRIVER_VERSION"] = self.env.get("SUKISU_DRIVER_VERSION") or "unset"
    fields["SUSFS_REPO"] = "https://gitlab.com/simonpunk/susfs4ksu.git"
    fields["SUSFS_REF"] = self.susfs_ref
    fields["INTEGRATION_MODE"] = "sukisu-v4.2.0-base-manager"
    fields["SUKISU_V420_MANUAL_SUPERCALL_PATCH"] = (
        "patches/sukisu-v4.2.0-redbull-4.19-manual-supercall.patch"
    )
    fields["SUKISU_V420_MANUAL_HOOKS_PATCH_SHA256"] = self.patch_hash(
        "sukisu_v420_manual_hooks_patch"
    )
    if self.target == "evolution":
        fields["SUKISU_V420_EVOLUTION_FILE_WRAPPER_PATCH_SHA256"] = self.patch_hash(
            "sukisu_v420_evolution_file_wrapper_patch"
        )
    fields["SUKISU_V420_MANUAL_EXEC_RUNTIME_PATCH_SHA256"] = self.patch_hash(
        "sukisu_v420_manual_exec_runtime_patch"
    )
    fields["SUKISU_V420_MANUAL_EXEC_RUNTIME_PATCH"] = (
        "patches/sukisu-v4.2.0-redbull-4.19-manual-exec-runtime.patch"
    )
    fields["SUKISU_V420_MANUAL_BOOTSTRAP_PATCH"] = (
        "patches/sukisu-v4.2.0-redbull-4.19-manual-bootstrap.patch"
    )
    fields["SUKISU_V420_MANUAL_ADB_ROOT_PATCH_SHA256"] = self.patch_hash(
        "sukisu_v420_manual_adb_root_patch"
    )
    fields["SUKISU_V420_MANUAL_ADB_ROOT_CALLSITE_PATCH_SHA256"] = self.patch_hash(
        "sukisu_v420_manual_adb_root_callsite_patch"
    )
    fields["SUKISU_V420_MANUAL_EXEC_CALLSITE_PATCH"] = (
        "patches/sukisu-v4.2.0-redbull-4.19-manual-exec-callsite.patch"
    )
    fields["SUKISU_V420_SECCOMP_DISABLE_OLD_PATCH"] = (
        "patches/sukisu-v4.2.0-redbull-4.19-seccomp-disable-old.patch"
    )
    fields["SUKISU_V420_MANUAL_REBOOT_HANDLER_PATCH"] = (
        "patches/sukisu-v4.2.0-redbull-4.19-manual-reboot-handler.patch"
    )
    fields["SUKISU_V420_MANUAL_REBOOT_CALLSITE_PATCH"] = (
        "patches/sukisu-v4.2.0-redbull-4.19-manual-reboot-callsite.patch"
    )
    fields["SUKISU_V420_MANUAL_KPROBES_OFF_PATCH"] = (
        "patches/sukisu-v4.2.0-redbull-4.19-manual-kprobes-off.patch"
    )
    fields["SUSFS"] = "not-integrated"
    fields["SUKISU_V420_DRIVER_VERSION_PATCH"] = (
        "patches/sukisu-v4.2.0-driver-version-override.patch"
    )
    return fields


def minimal_lock(self):
    fields = {}
    fields["SUKISU_REPO"] = "https://github.com/SukiSU-Ultra/SukiSU-Ultra.git"
    fields["SUKISU_REF"] = self.sukisu_ref
    fields["INTEGRATION_MODE"] = "sukisu-v4.2.0-kprobes-minimal"
    fields["SUSFS"] = "not-integrated"
    fields["RUNTIME_HOOKS"] = "upstream-kprobes-only"
    fields["SUKISU_V420_EVOLUTION_FILE_WRAPPER_PATCH_SHA256"] = self.patch_hash(
        "sukisu_v420_evolution_file_wrapper_patch"
    )
    return fields


def susfs_lock(self):
    fields = {}
    fields["SUKISU_REPO"] = "https://github.com/SukiSU-Ultra/SukiSU-Ultra.git"
    fields["SUKISU_REF"] = self.sukisu_ref
    fields["SUKISU_DRIVER_VERSION"] = self.env.get("SUKISU_DRIVER_VERSION") or "unset"
    fields["SUSFS_REPO"] = "https://gitlab.com/simonpunk/susfs4ksu.git"
    fields["SUSFS_REF"] = self.susfs_ref
    if self.target == "evolution":
        fields["SUSFS_KERNEL_PATCH"] = (
            "patches/susfs-1.5.5-evolution-4.19.325-combined.patch"
        )
        fields["SUSFS_KERNEL_PATCH_SHA256"] = self.patch_hash(
            "susfs_evolution_combined_patch"
        )
    else:
        fields["SUSFS_KERNEL_PATCH"] = (
            "kernel_patches/50_add_susfs_in_kernel-4.19.patch"
        )
        fields["SUSFS_KERNEL_PATCH_SHA256"] = self.upstream_hash()
        fields["SUSFS_STOCK_CALLSITE_STYLE_PATCH_SHA256"] = self.patch_hash(
            "susfs_stock_callsite_style_patch"
        )
    fields["INTEGRATION_MODE"] = "sukisu-v4.2.0-susfs-dual-abi"
    fields["SUSFS"] = "v1.5.5-integrated"
    fields["SUSFS_USERSPACE_ABI"] = "reboot(0xDEADBEEF,0xFAFAFAFA,cmd,payload)"
    fields["SUSFS_LEGACY_HELPER_ABI"] = "prctl(0xDEADBEEF,cmd,payload,NULL,&err)"
    fields["SUSFS_PATH_VALIDATION_PATCH_SHA256"] = self.patch_hash(
        "susfs_path_validation_patch"
    )
    fields["SUSFS_CONCURRENCY_PATCH_SHA256"] = self.patch_hash(
        "susfs_concurrency_patch"
    )
    fields["SUSFS_CALLSITE_SAFETY_PATCH_SHA256"] = self.patch_hash(
        "susfs_callsite_safety_patch"
    )
    fields["SUSFS_CORRECTNESS_PATCH_SHA256"] = self.patch_hash(
        "susfs_correctness_patch"
    )
    fields["SUSFS_KSTAT_FORWARD_PATCH_SHA256"] = self.patch_hash(
        "susfs_kstat_forward_patch"
    )
    fields["SUSFS_REBOOT_ABI_PATCH_SHA256"] = self.patch_hash("susfs_reboot_abi_patch")
    fields["SUSFS_REBOOT_ABI_HOOK_PATCH_SHA256"] = self.patch_hash(
        "susfs_reboot_abi_hook_patch"
    )
    fields["SUKISU_SUSFS_KERNEL_PATCH_SHA256"] = self.patch_hash(
        "sukisu_v420_susfs_kernel_patch"
    )
    fields["SUKISU_SUSFS_PRCTL_HANDLER_PATCH_SHA256"] = self.patch_hash(
        "sukisu_v420_susfs_prctl_handler_patch"
    )
    fields["SUKISU_SUSFS_REBOOT_CALLSITE_PATCH_SHA256"] = self.patch_hash(
        "sukisu_v420_susfs_reboot_callsite_patch"
    )
    fields["SUKISU_V420_MANUAL_ADB_ROOT_PATCH_SHA256"] = self.patch_hash(
        "sukisu_v420_manual_adb_root_patch"
    )
    fields["SUKISU_V420_MANUAL_ADB_ROOT_CALLSITE_PATCH_SHA256"] = self.patch_hash(
        "sukisu_v420_manual_adb_root_callsite_patch"
    )
    if self.target == "evolution":
        fields["SUKISU_V420_EVOLUTION_FILE_WRAPPER_PATCH_SHA256"] = self.patch_hash(
            "sukisu_v420_evolution_file_wrapper_patch"
        )
    fields["SUKISU_V420_SELINUX_SEPOLICY_API_PATCH_SHA256"] = self.patch_hash(
        "sukisu_v420_selinux_sepolicy_api_patch"
    )
    fields["SUKISU_SUSFS_PRCTL_CALLSITE_PATCH_SHA256"] = self.patch_hash(
        "sukisu_v420_susfs_prctl_callsite_patch"
    )
    fields["SUSFS_UNSUPPORTED_COMMANDS"] = (
        "ADD_SUS_PATH_LOOP,HIDE_SUS_MOUNTS_FOR_NON_SU_PROCS,ENABLE_AVC_LOG_SPOOFING,ADD_SUS_MAP"
    )
    fields["SUSFS_OPEN_REDIRECT_UID_SCHEME"] = (
        "2-only (legacy table has no per-UID scheme)"
    )
    return fields


def legacy_lock(self):
    return {
        "SUKISU_REPO": "https://github.com/SukiSU-Ultra/SukiSU-Ultra.git",
        "SUKISU_REF": self.sukisu_ref,
        "SUSFS_REPO": "https://gitlab.com/simonpunk/susfs4ksu.git",
        "SUSFS_REF": self.susfs_ref,
        "SUSFS_KERNEL_PATCH": "kernel_patches/50_add_susfs_in_kernel-4.19.patch",
        "SUSFS_STOCK_CALLSITE_STYLE_PATCH_SHA256": self.patch_hash(
            "susfs_stock_callsite_style_patch"
        ),
        "SUSFS_PATH_VALIDATION_PATCH": "patches/susfs-1.5.5-pathname-validation.patch",
        "SUSFS_PATH_VALIDATION_PATCH_SHA256": self.patch_hash(
            "susfs_path_validation_patch"
        ),
        "SUSFS_CONCURRENCY_PATCH": "patches/susfs-1.5.5-concurrency.patch",
        "SUSFS_CONCURRENCY_PATCH_SHA256": self.patch_hash("susfs_concurrency_patch"),
        "SUSFS_CALLSITE_SAFETY_PATCH": "patches/susfs-1.5.5-callsite-safety.patch",
        "SUSFS_CALLSITE_SAFETY_PATCH_SHA256": self.patch_hash(
            "susfs_callsite_safety_patch"
        ),
        "SUSFS_CORRECTNESS_PATCH": "patches/susfs-1.5.5-correctness.patch",
        "SUSFS_CORRECTNESS_PATCH_SHA256": self.patch_hash("susfs_correctness_patch"),
        "SUSFS_KSTAT_FORWARD_PATCH": "patches/susfs-1.5.5-kstat-forward-declaration.patch",
        "SUSFS_KSTAT_FORWARD_PATCH_SHA256": self.patch_hash(
            "susfs_kstat_forward_patch"
        ),
        "SUSFS_SOURCE_SHA256": "cd117f5a7900048fdf2abf87d70ef65c01c634b2ff6ccf8fe079fbd6766d7251",
        "SUSFS_PATCHED_SOURCE_SHA256": "29c622bed96ff8307dbc3e243f51041a07035619bbaa1c1b69e3df802adbb89f",
        "SUSFS_PATCHED_HEADER_SHA256": "e121fab21340c0defccedce4c9a630c2eeafc8bf3df2d514cea1f52ce543d90c",
        "SUSFS_PRCTL_HOOK_PATCH": "patches/redbull-kernelsu-susfs-prctl-hook.patch",
        "SUKISU_SUSFS_PRCTL_PATCH": "patches/sukisu-40922-susfs-v155-prctl.patch",
        "SUKISU_LEGACY_REBOOT_PATCH": "patches/sukisu-40922-disable-legacy-susfs-reboot.patch",
        "SUKISU_CURRENT_PROC_PATCH": "patches/sukisu-40922-susfs-current-proc-state.patch",
        "KSU_MANUAL_HOOKS_PATCH": "patches/redbull-kernelsu-manual-hooks.patch",
        "KSU_SETRESUID_HOOK_PATCH": "patches/redbull-kernelsu-setresuid-hook.patch",
        "SUKISU_V420_MANUAL_SUPERCALL_PATCH": "patches/sukisu-v4.2.0-redbull-4.19-manual-supercall.patch",
        "KPM": "disabled",
    }


def sha256_file(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        return digest.hexdigest()


def git(tree, *args, check=True, quiet=False):
    result = subprocess.run(
        ["git", "-C", str(tree), *map(str, args)],
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        raise RuntimeError(
            f"Git {' '.join(map(str, args))} failed in {tree}: "
            f"{result.stderr.strip()}"
        )
    if not quiet and result.stdout:
        print(result.stdout, end="", flush=True)
    return result


def apply_once(tree, patch, description):
    if (
        git(
            tree, "apply", "--reverse", "--check", patch, check=False, quiet=True
        ).returncode
        == 0
    ):
        print(f"{description} is already applied.", flush=True)
    elif git(tree, "apply", "--check", patch, check=False, quiet=True).returncode == 0:
        git(tree, "apply", patch)
        print(f"Applied {description}.", flush=True)
    else:
        raise RuntimeError(f"{description} does not apply cleanly.")


def install_checked(source, destination):
    if destination.exists() and source.read_bytes() != destination.read_bytes():
        raise RuntimeError(f"Refusing to overwrite modified SUSFS file: {destination}.")
    shutil.copyfile(source, destination)


class Integration:
    def __init__(self, env):
        self.env = env
        for key in ("KERNEL_DIR", "SUKISU_SOURCE_DIR", "SUSFS_SOURCE_DIR"):
            if not env.get(key):
                raise ValueError(f"{key} is required.")
        self.kernel = Path(env["KERNEL_DIR"]).resolve()
        self.source = Path(env["SUKISU_SOURCE_DIR"]).resolve()
        self.susfs = Path(env["SUSFS_SOURCE_DIR"]).resolve()
        self.repo = Path(env.get("REPO_ROOT") or "/workspace").resolve()
        self.artifacts = Path(env.get("ARTIFACT_DIR") or self.repo / "artifacts")
        self.target = env.get("BUILD_TARGET") or "stock"
        self.stage = env.get("EVOLUTION_STAGE") or "susfs"
        if self.target not in ("stock", "evolution"):
            raise ValueError(f"Unsupported build target: {self.target}.")
        self.enabled = env.get("ENABLE_SUSFS") or "0"
        self.ksu = self.kernel / "KernelSU"
        self.upstream = self.susfs / "kernel_patches/50_add_susfs_in_kernel-4.19.patch"
        self.patches = {
            name: Path(env.get(key) or self.repo / "patches" / filename).resolve()
            for name, (key, filename) in PATCHES.items()
        }

    def patch_hash(self, name):
        return sha256_file(self.patches[name])

    def upstream_hash(self):
        return sha256_file(self.upstream)

    def validate_hash(self, path, expected, description):
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(
                f"{description} SHA256 mismatch: expected {expected}, got {actual} ({path})."
            )

    def validate_sources(self):
        for relative, expected in SOURCE_HASHES.items():
            self.validate_hash(
                self.susfs / "kernel_patches" / relative, expected, "Pinned SUSFS file"
            )

    def validate(self):
        required = [
            self.kernel / "Makefile",
            self.source / "kernel/setup.sh",
            self.upstream,
        ]
        # Preserve upfront checks, including the legacy patch inputs. The stock
        # formatting patch was formerly checked by git only when it was used.
        required.extend(
            path
            for name, path in self.patches.items()
            if name != "susfs_stock_callsite_style_patch"
            and (
                self.target == "evolution"
                or name
                not in (
                    "sukisu_v420_evolution_file_wrapper_patch",
                    "susfs_evolution_combined_patch",
                )
            )
        )
        for path in required:
            if not path.is_file():
                raise RuntimeError(f"Required integration input is missing: {path}.")
        self.sukisu_ref = git(
            self.source, "rev-parse", "HEAD", quiet=True
        ).stdout.strip()
        self.susfs_ref = git(self.susfs, "rev-parse", "HEAD", quiet=True).stdout.strip()
        for description, actual, expected in (
            (
                "SukiSU",
                self.sukisu_ref,
                self.env.get("SUKISU_EXPECTED_REF") or SUKISU_REF,
            ),
            ("SUSFS", self.susfs_ref, self.env.get("SUSFS_EXPECTED_REF") or SUSFS_REF),
        ):
            if actual != expected:
                raise RuntimeError(
                    f"{description} revision mismatch: expected {expected}, got {actual}."
                )
        if self.enabled not in ("0", "1"):
            raise ValueError(f"ENABLE_SUSFS must be 0 or 1, got {self.enabled}.")
        self.validate_sources()

    def ensure_sukisu(self):
        if self.ksu.exists():
            result = git(self.ksu, "rev-parse", "HEAD", check=False, quiet=True)
            if result.returncode or result.stdout.strip() != self.sukisu_ref:
                raise RuntimeError(
                    f"KernelSU directory has an unexpected revision: {self.ksu}."
                )
        else:
            shutil.copytree(
                self.source, self.ksu, symlinks=True, copy_function=shutil.copy2
            )

    def apply_plan(self, plan):
        for tree, name, description, target in plan:
            if target != "all" and target != self.target:
                continue
            if tree == "sukisu":
                self.ensure_sukisu()
            apply_once(
                self.kernel if tree == "kernel" else self.ksu,
                self.patches[name],
                description,
            )

    def link_driver(self):
        link = self.kernel / "drivers/kernelsu"
        if link.exists() and not link.is_symlink():
            raise RuntimeError(
                f"KernelSU driver path is occupied by a non-symlink: {link}."
            )
        if link.is_symlink():
            link.unlink()
        link.symlink_to("../KernelSU/kernel")

    def write_lock(self, fields):
        self.artifacts.mkdir(parents=True, exist_ok=True)
        (self.artifacts / "sukisu-susfs.lock").write_text(
            "".join(f"{key}={value}\n" for key, value in fields.items()),
            encoding="utf-8",
        )

    def require_kconfig(self, tree, present):
        found = "config KSU_SUSFS" in (tree / "kernel/Kconfig").read_text().splitlines()
        if found != present:
            raise RuntimeError(f"Unexpected SUSFS Kconfig integration in {tree}.")

    def install_susfs(self, evolution=False):
        if evolution:
            for relative in SOURCE_HASHES:
                install_checked(
                    self.susfs / "kernel_patches" / relative, self.kernel / relative
                )
            # The combined patch is intentionally applied only to pristine
            # staged SUSFS sources, matching the original pipeline.
            patch = self.patches["susfs_evolution_combined_patch"]
            git(self.kernel, "apply", "--check", patch)
            git(self.kernel, "apply", patch)
            print("Applied checked Evolution SUSFS combined patch.", flush=True)
        elif (
            git(
                self.kernel,
                "apply",
                "--reverse",
                "--check",
                self.upstream,
                check=False,
                quiet=True,
            ).returncode
            == 0
        ):
            for relative in SOURCE_HASHES:
                path = self.kernel / relative
                if not path.is_file() or not path.stat().st_size:
                    raise RuntimeError(
                        "SUSFS patch is applied but its source files are missing."
                    )
            print("SUSFS kernel patch is already applied.", flush=True)
        elif (
            git(
                self.kernel, "apply", "--check", self.upstream, check=False, quiet=True
            ).returncode
            == 0
        ):
            for relative in SOURCE_HASHES:
                install_checked(
                    self.susfs / "kernel_patches" / relative, self.kernel / relative
                )
            git(self.kernel, "apply", self.upstream)
            print("Applied SUSFS kernel patch.", flush=True)
        else:
            raise RuntimeError(
                "SUSFS kernel patch does not apply cleanly to this kernel tree."
            )

    def run(self):
        self.validate()
        if self.sukisu_ref == SUKISU_REF:
            self.require_kconfig(self.source, False)
            minimal = self.target == "evolution" and self.stage == "sukisu-minimal"
            if minimal and self.enabled != "0":
                raise ValueError(
                    "Minimal Evolution SukiSU stage must not enable SUSFS."
                )
            self.apply_plan(MINIMAL_PLAN if minimal else BASE_PLAN)
            self.link_driver()
            self.write_lock(minimal_lock(self) if minimal else base_lock(self))
            if minimal or self.enabled == "0":
                print(
                    "SukiSU Ultra v4.2.0 integration is ready; SUSFS is not integrated.",
                    flush=True,
                )
                return
            self.install_susfs(evolution=self.target == "evolution")
            self.apply_plan(SUSFS_PLAN)
            self.require_kconfig(self.ksu, True)
            self.validate_sources()
            self.write_lock(susfs_lock(self))
            print(
                "SukiSU v4.2.0 and SUSFS v1.5.5 reboot ABI integration is ready.",
                flush=True,
            )
        else:
            self.install_susfs()
            self.apply_plan(LEGACY_PLAN)
            self.link_driver()
            self.require_kconfig(self.ksu, True)
            for relative, expected in (
                (
                    "fs/susfs.c",
                    "29c622bed96ff8307dbc3e243f51041a07035619bbaa1c1b69e3df802adbb89f",
                ),
                (
                    "include/linux/susfs.h",
                    "e121fab21340c0defccedce4c9a630c2eeafc8bf3df2d514cea1f52ce543d90c",
                ),
                (
                    "include/linux/susfs_def.h",
                    SOURCE_HASHES["include/linux/susfs_def.h"],
                ),
            ):
                self.validate_hash(
                    self.kernel / relative, expected, "Patched SUSFS file"
                )
            self.write_lock(legacy_lock(self))
            print("Pinned SukiSU and SUSFS integration is ready.", flush=True)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        Integration(os.environ).run()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
