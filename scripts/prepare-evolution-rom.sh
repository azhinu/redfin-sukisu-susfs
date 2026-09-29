#!/usr/bin/env bash
set -Eeuo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
rom_dir=${EVOLUTION_ROM_DIR:-$repo_root/rom/evolution}
config_file=${EVOLUTION_CONFIG_FILE:-$repo_root/configs/evolution-x-16-redfin.env}
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
  printf 'Evolution OTA archive is missing: %s.\n' "$archive" >&2
  exit 1
}
printf '%s  %s\n' "$EVOLUTION_ROM_SHA256" "$archive" | sha256sum -c -

if [[ ! -s "$boot_image" || ! -s "$vendor_boot_image" ]]; then
  extracted_dir=$(mktemp -d "$rom_dir/.extract.XXXXXX")
  trap 'rm -rf "$extracted_dir"' EXIT
  python3 "$repo_root/scripts/extract-ota-images.py" \
    --archive "$archive" --output "$extracted_dir" \
    --expected "boot=$EVOLUTION_PAYLOAD_BOOT_SHA256" \
    --expected "vendor_boot=$EVOLUTION_PAYLOAD_VENDOR_BOOT_SHA256"
  [[ -s "$boot_image" ]] || cp "$extracted_dir/boot.img" "$boot_image"
  [[ -s "$vendor_boot_image" ]] || cp "$extracted_dir/vendor_boot.img" "$vendor_boot_image"
  printf 'Materialized missing Evolution boot images from the verified OTA payload.\n'
fi

verify_image() {
  local label=$1 image=$2 expected_sha=$3 actual
  actual=$(shasum -a 256 "$image" | awk '{print $1}')
  if [[ "$actual" != "$expected_sha" ]]; then
    printf 'Evolution %s image has an unexpected SHA256: %s.\n' "$label" "$actual" >&2
    exit 1
  fi
  printf 'Verified Evolution %s image: %s.\n' "$label" "$actual"
}

boot_sha=$(shasum -a 256 "$boot_image" | awk '{print $1}')
vendor_boot_sha=$(shasum -a 256 "$vendor_boot_image" | awk '{print $1}')
if [[ "$boot_sha:$vendor_boot_sha" != "$EVOLUTION_PAYLOAD_BOOT_SHA256:$EVOLUTION_PAYLOAD_VENDOR_BOOT_SHA256" ]]; then
  printf 'Evolution boot and vendor_boot are not a pinned matching pair: %s, %s.\n' \
    "$boot_sha" "$vendor_boot_sha" >&2
  exit 1
fi
verify_image boot "$boot_image" "$EVOLUTION_PAYLOAD_BOOT_SHA256"
verify_image vendor_boot "$vendor_boot_image" "$EVOLUTION_PAYLOAD_VENDOR_BOOT_SHA256"
printf 'Evolution ROM inputs are ready in %s.\n' "$rom_dir"
