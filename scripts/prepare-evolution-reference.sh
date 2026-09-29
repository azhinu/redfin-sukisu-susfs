#!/usr/bin/env bash
set -Eeuo pipefail

stock_root=${STOCK_ROOT:-/stock}
kernel_dir=${KERNEL_DIR:-$stock_root/private/msm-google}
reference_dir="$stock_root/reference"
rom_dir=${EVOLUTION_ROM_DIR:-/workspace/rom/evolution}
config_file=${EVOLUTION_CONFIG_FILE:-/workspace/configs/evolution-x-16-redfin.env}
[[ -f "$config_file" ]] || {
  printf 'Evolution configuration is missing: %s.\n' "$config_file" >&2
  exit 1
}
# shellcheck disable=SC1090
source "$config_file"

archive="$rom_dir/$EVOLUTION_ROM_FILENAME"
boot_image="$rom_dir/boot.img"
vendor_boot_image="$rom_dir/vendor_boot.img"
[[ -s "$archive" ]] || {
  printf 'Evolution OTA archive is missing from the mounted workspace: %s.\n' "$archive" >&2
  exit 1
}
printf '%s  %s\n' "$EVOLUTION_ROM_SHA256" "$archive" | sha256sum -c -

verify_image() {
  local label=$1 image=$2 expected_sha=$3 actual
  [[ -s "$image" ]] || {
    printf 'Evolution %s image is missing: %s.\n' "$label" "$image" >&2
    exit 1
  }
  actual=$(sha256sum "$image" | awk '{print $1}')
  if [[ "$actual" != "$expected_sha" ]]; then
    printf 'Evolution %s image has an unexpected SHA256: %s.\n' "$label" "$actual" >&2
    exit 1
  fi
  printf 'Verified Evolution %s image: %s.\n' "$label" "$actual"
  printf '%s\n' "$actual"
}

boot_sha=$(verify_image boot "$boot_image" "$EVOLUTION_PAYLOAD_BOOT_SHA256" | tail -n1)
vendor_boot_sha=$(verify_image vendor_boot "$vendor_boot_image" \
  "$EVOLUTION_PAYLOAD_VENDOR_BOOT_SHA256" | tail -n1)
if [[ "$boot_sha:$vendor_boot_sha" != "$EVOLUTION_PAYLOAD_BOOT_SHA256:$EVOLUTION_PAYLOAD_VENDOR_BOOT_SHA256" ]]; then
  printf 'Evolution boot and vendor_boot are not a pinned matching pair: %s, %s.\n' \
    "$boot_sha" "$vendor_boot_sha" >&2
  exit 1
fi

mkdir -p "$reference_dir"
work_dir=$(mktemp -d "$stock_root/evolution-reference.XXXXXX")
trap 'rm -rf "$work_dir"' EXIT
python3 "$stock_root/tools/mkbootimg/unpack_bootimg.py" \
  --boot_img "$boot_image" --out "$work_dir/unpacked"
if ! lz4 -dc "$work_dir/unpacked/kernel" > "$work_dir/kernel.raw"; then
  [[ -s "$work_dir/kernel.raw" ]] || {
    printf 'Evolution boot kernel LZ4 decompression failed without output.\n' >&2
    exit 1
  }
  printf 'Evolution boot kernel LZ4 decoder returned non-zero after producing output; continuing.\n'
fi
"$kernel_dir/scripts/extract-ikconfig" \
  "$work_dir/kernel.raw" > "$work_dir/kernel.config"
[[ -s "$work_dir/kernel.config" ]] || {
  printf 'Evolution kernel configuration was not extracted from boot.img.\n' >&2
  exit 1
}

cp "$boot_image" "$reference_dir/boot.img"
cp "$vendor_boot_image" "$reference_dir/vendor_boot.img"
cp "$work_dir/kernel.config" "$reference_dir/evolution-kernel.config"
cat > "$reference_dir/evolution-rom.sha256" << EOF
EVOLUTION_ROM_VERSION=$EVOLUTION_ROM_VERSION
EVOLUTION_ROM_URL=$EVOLUTION_ROM_URL
EVOLUTION_ROM_FILENAME=$EVOLUTION_ROM_FILENAME
EVOLUTION_ROM_SHA256=$EVOLUTION_ROM_SHA256
EVOLUTION_BOOT_SHA256=$boot_sha
EVOLUTION_VENDOR_BOOT_SHA256=$vendor_boot_sha
EOF
printf 'Prepared Evolution X %s reference images and kernel configuration.\n' \
  "$EVOLUTION_ROM_VERSION"
