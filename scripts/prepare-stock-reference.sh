#!/usr/bin/env bash
set -Eeuo pipefail

stock_root=${STOCK_ROOT:-/stock}
reference_dir="$stock_root/reference"
default_factory_url=https://dl.google.com/dl/android/aosp/redfin-up1a.231105.001.b2-factory-4e5a2679.zip
factory_url=${STOCK_FACTORY_URL:-$default_factory_url}
factory_zip=${STOCK_FACTORY_ZIP:-$stock_root/redfin-factory.zip}
# SHA256 independently calculated from the cached Google factory archive.
factory_sha256=${STOCK_FACTORY_SHA256:-4e5a26793d8400f13b72cbd17aeb284e040b3236436f0c6f3119ccc77d4495ad}
if [[ ("$factory_url" != "$default_factory_url" || -n ${STOCK_FACTORY_ZIP:-}) &&
  -z ${STOCK_FACTORY_SHA256:-} ]]; then
  printf 'Custom factory input requires STOCK_FACTORY_SHA256.\n' >&2
  exit 1
fi
[[ "$factory_sha256" =~ ^[[:xdigit:]]{64}$ ]] || {
  printf 'Factory SHA256 must contain 64 hexadecimal characters.\n' >&2
  exit 1
}
mkdir -p "$reference_dir"
work_dir=$(mktemp -d "$stock_root/reference.XXXXXX")
trap 'rm -rf "$work_dir"' EXIT
if [[ -n ${STOCK_REFERENCE_BOOT:-} || -n ${STOCK_REFERENCE_KERNEL_CONFIG:-} ]]; then
  [[ -s ${STOCK_REFERENCE_BOOT:-} ]] || {
    printf 'Stock reference boot image is missing: %s.\n' "${STOCK_REFERENCE_BOOT:-}" >&2
    exit 1
  }
  [[ -s ${STOCK_REFERENCE_KERNEL_CONFIG:-} ]] || {
    printf 'Stock reference kernel config is missing: %s.\n' "${STOCK_REFERENCE_KERNEL_CONFIG:-}" >&2
    exit 1
  }
  cp "$STOCK_REFERENCE_BOOT" "$reference_dir/boot.img"
  cp "$STOCK_REFERENCE_KERNEL_CONFIG" "$reference_dir/kernel.config"
  printf '%s\n' "$factory_sha256" > "$reference_dir/factory.sha256"
  printf 'Using supplied stock reference boot and kernel configuration.\n'
  exit 0
fi
if [[ -n ${STOCK_FACTORY_ZIP:-} && ! -s "$factory_zip" ]]; then
  printf 'Custom factory archive is missing: %s.\n' "$factory_zip" >&2
  exit 1
fi
if [[ ! -s "$factory_zip" ]]; then
  printf 'Downloading the pinned redfin Android 14 factory image.\n'
  curl -fsSL --retry 3 -o "$work_dir/factory.zip" "$factory_url"
  printf '%s  %s\n' "$factory_sha256" "$work_dir/factory.zip" | sha256sum -c -
  factory_zip="$stock_root/redfin-factory.zip"
  mv "$work_dir/factory.zip" "$factory_zip"
else
  printf '%s  %s\n' "$factory_sha256" "$factory_zip" | sha256sum -c -
fi

# Determine the archive format first; extraction validates each entry's CRC.
python3 - "$factory_zip" "$work_dir" << 'PY'
import pathlib
import shutil
import sys
import zipfile

archive, directory = sys.argv[1], pathlib.Path(sys.argv[2])
with zipfile.ZipFile(archive) as factory:
    nested = [name for name in factory.namelist()
              if pathlib.PurePosixPath(name).name.startswith('image-') and name.endswith('.zip')]
    if nested:
        if len(nested) != 1:
            raise ValueError('Factory archive must contain exactly one image ZIP.')
        image = directory / 'image.zip'
        with factory.open(nested[0]) as source, image.open('wb') as target:
            shutil.copyfileobj(source, target)
        with zipfile.ZipFile(image) as images:
            with images.open('boot.img') as source, (directory / 'boot.img').open('wb') as target:
                shutil.copyfileobj(source, target)
    else:
        with factory.open('boot.img') as source, (directory / 'boot.img').open('wb') as target:
            shutil.copyfileobj(source, target)
PY
python3 "$stock_root/tools/mkbootimg/unpack_bootimg.py" \
  --boot_img "$work_dir/boot.img" --out "$work_dir/unpacked"
if ! lz4 -dc "$work_dir/unpacked/kernel" > "$work_dir/kernel.raw"; then
  [[ -s "$work_dir/kernel.raw" ]] || {
    printf 'Kernel LZ4 decompression failed without output.\n' >&2
    exit 1
  }
  printf 'Kernel LZ4 decoder returned non-zero after producing kernel.raw; continuing.\n'
fi
"$stock_root/private/msm-google/scripts/extract-ikconfig" \
  "$work_dir/kernel.raw" > "$work_dir/kernel.config"
[[ -s "$work_dir/kernel.config" ]] || {
  printf 'Factory kernel configuration was not extracted.\n' >&2
  exit 1
}
mv "$work_dir/boot.img" "$reference_dir/boot.img"
mv "$work_dir/kernel.config" "$reference_dir/kernel.config"
printf '%s\n' "$factory_sha256" > "$reference_dir/factory.sha256"
printf 'Verified stock reference boot and extracted kernel configuration are ready.\n'
