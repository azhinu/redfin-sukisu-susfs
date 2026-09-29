#!/usr/bin/env bash
set -Eeuo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root_dir=$(cd "$script_dir/.." && pwd)
artifact_dir=${ARTIFACT_DIR:-$root_dir/artifacts/stock-sukisu}
input_boot=${INPUT_BOOT:-$root_dir/artifacts/stock-baseline/boot.img}
input_kernel=${INPUT_KERNEL:-$artifact_dir/Image.lz4}
input_vendor_boot=${INPUT_VENDOR_BOOT:-}
target=${TARGET_ROM:-stock}
rom_version=${ROM_VERSION:-Google-stock-redfin}
anykernel_source=${ANYKERNEL_SOURCE_DIR:-$root_dir/deps/anykernel}

[[ -f "$input_boot" ]] || {
  printf 'Input boot image is missing: %s.\n' "$input_boot" >&2
  exit 1
}
[[ -f "$input_kernel" ]] || {
  printf 'Input kernel image is missing: %s.\n' "$input_kernel" >&2
  exit 1
}
if [[ -n "$input_vendor_boot" && ! -f "$input_vendor_boot" ]]; then
  printf 'Input vendor_boot image is missing: %s.\n' "$input_vendor_boot" >&2
  exit 1
fi

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/redfin-image-package.XXXXXX")
trap 'rm -rf "$work_dir"' EXIT
mkdir -p "$artifact_dir" "$work_dir/output/fastboot"
artifact_dir=$(cd "$artifact_dir" && pwd)
output_dir="$work_dir/output"

python3 "$root_dir/scripts/repack-boot-v3.py" \
  --template "$input_boot" \
  --kernel "$input_kernel" \
  --output "$output_dir/boot.img"

cp "$output_dir/boot.img" "$output_dir/fastboot/boot.img"
if [[ -n "$input_vendor_boot" ]]; then
  cp "$input_vendor_boot" "$output_dir/vendor_boot.img"
  cp "$input_vendor_boot" "$output_dir/fastboot/vendor_boot.img"
fi
cat > "$output_dir/fastboot/README.txt" << EOF
Pixel 5 redfin fastboot test package for $rom_version.

This package contains an unsigned boot image built from the $target ROM boot
header and ramdisk. It is intended for an unlocked bootloader. Prefer the
fastboot boot boot.img command first. Keep the matching vendor_boot image beside it;
do not mix boot, vendor_boot, or dtbo from another ROM.
EOF

printf 'Packaging pinned AnyKernel3 installer framework.\n'
[[ $(git -C "$anykernel_source" rev-parse HEAD) == 020dfeccf9d7e962a48400fc94d3e451df92eead ]] || {
  printf 'AnyKernel3 commit mismatch.\n' >&2
  exit 1
}
mkdir "$work_dir/anykernel"
git -C "$anykernel_source" archive HEAD | tar -x -C "$work_dir/anykernel"
rm -f "$work_dir/anykernel/README.md" "$work_dir/anykernel/Image.lz4" \
  "$work_dir/anykernel/boot.img"

cp "$root_dir/configs/anykernel.sh" "$work_dir/anykernel/anykernel.sh"
cp "$input_kernel" "$work_dir/anykernel/Image.lz4"
cat > "$work_dir/anykernel/README.md" << EOF
# Pixel 5 redfin — $rom_version + SukiSU Ultra v4.2.0

This AnyKernel package replaces the kernel payload only. It is intended for
the matching $target boot layout. Keep a known-good boot image nearby and use
the fastboot boot command before flashing permanently.
EOF
(cd "$work_dir/anykernel" &&
  find . -exec touch -h -t 202001010000.00 {} + &&
  find . \( -type f -o -type l \) -print | LC_ALL=C sort |
  TZ=UTC zip -qX "$work_dir/AnyKernel-redfin-sukisu.zip" -@)
mv "$work_dir/AnyKernel-redfin-sukisu.zip" \
  "$output_dir/AnyKernel-redfin-sukisu.zip"

checks=(AnyKernel-redfin-sukisu.zip boot.img boot.json sukisu-susfs.lock source-lock.json)
if [[ "$target" == stock ]]; then
  checks+=(factory.sha256)
else
  checks+=(vendor_boot.img evolution-rom.sha256 evolution-kernel.revision)
fi
for name in "${checks[@]}"; do
  [[ -f "$output_dir/$name" ]] || cp "$artifact_dir/$name" "$output_dir/$name"
done
(cd "$output_dir" && sha256sum "${checks[@]}" > SHA256SUMS)
backup_dir=$(mktemp -d "$artifact_dir/.package-backup.XXXXXX")
published=0
publish_started=0
publish_names=(AnyKernel-redfin-sukisu.zip boot.img boot.json vendor_boot.img SHA256SUMS)
restore_on_exit() {
  local status=$?
  if [[ "$publish_started" == 1 && "$published" == 0 ]]; then
    for name in "${publish_names[@]}"; do
      if [[ -f "$backup_dir/$name" ]]; then
        cp "$backup_dir/$name" "$artifact_dir/$name"
      else
        rm -f "$artifact_dir/$name"
      fi
    done
    rm -rf "$artifact_dir/fastboot"
    if [[ -d "$backup_dir/fastboot" ]]; then
      cp -a "$backup_dir/fastboot" "$artifact_dir/fastboot"
    fi
  fi
  rm -rf "$work_dir" "$backup_dir"
  return "$status"
}
trap restore_on_exit EXIT
for name in "${publish_names[@]}"; do
  if [[ -f "$artifact_dir/$name" ]]; then
    cp "$artifact_dir/$name" "$backup_dir/$name"
  fi
done
if [[ -d "$artifact_dir/fastboot" ]]; then
  cp -a "$artifact_dir/fastboot" "$backup_dir/fastboot"
fi
publish_started=1
for name in AnyKernel-redfin-sukisu.zip boot.img boot.json vendor_boot.img; do
  if [[ -f "$output_dir/$name" ]]; then
    mv "$output_dir/$name" "$artifact_dir/$name"
  elif [[ "$name" == vendor_boot.img ]]; then
    rm -f "$artifact_dir/$name"
  fi
done
rm -rf "$artifact_dir/fastboot"
mv "$output_dir/fastboot" "$artifact_dir/fastboot"
mv "$output_dir/SHA256SUMS" "$artifact_dir/SHA256SUMS"
published=1
rm -f "$artifact_dir/boot-test.json"
printf 'Packaged AnyKernel and fastboot artifacts in %s.\n' "$artifact_dir"
