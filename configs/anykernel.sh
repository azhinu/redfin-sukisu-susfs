### AnyKernel3 Ramdisk Mod Script
# shellcheck shell=sh
# AK3 reads the quoted property block and consumes variables through ak3-core.
# shellcheck disable=SC2289,SC2034,SC1091

properties() { '
kernel.string=Pixel 5 redfin + SukiSU Ultra v4.2.0
do.devicecheck=1
do.modules=0
do.systemless=1
do.cleanup=1
do.cleanuponabort=0
device.name1=redfin
supported.versions=
supported.patchlevels=
supported.vendorpatchlevels=
'; }

boot_attributes() {
  set_perm_recursive 0 0 755 644 "$RAMDISK"/*
  set_perm_recursive 0 0 750 750 "$RAMDISK"/init* "$RAMDISK"/sbin
}

BLOCK=boot
IS_SLOT_DEVICE=1
RAMDISK_COMPRESSION=auto
PATCH_VBMETA_FLAG=auto

. tools/ak3-core.sh

dump_boot
write_boot
