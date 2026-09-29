#!/usr/bin/env bash
set -Eeuo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
config_file=${EVOLUTION_KERNEL_CONFIG:-$repo_root/configs/evolution-kernel.env}
source_path=${1:-${EVOLUTION_KERNEL_SOURCE:-$repo_root/rom/evolution/kernel}}

[[ -f "$config_file" ]] || {
  printf 'Evolution kernel configuration is missing: %s.\n' "$config_file" >&2
  exit 1
}
# shellcheck disable=SC1090
source "$config_file"

[[ -d "$source_path/.git" || -f "$source_path/.git" ]] || {
  printf 'Evolution kernel source checkout is missing: %s.\n' "$source_path" >&2
  printf 'Set EVOLUTION_KERNEL_SOURCE to a local checkout of %s.\n' "$EVOLUTION_KERNEL_URL" >&2
  exit 1
}
actual=$(git -C "$source_path" rev-parse HEAD)
[[ "$actual" == "$EVOLUTION_KERNEL_REVISION" ]] || {
  printf 'Evolution kernel revision mismatch: expected %s, got %s.\n' \
    "$EVOLUTION_KERNEL_REVISION" "$actual" >&2
  exit 1
}
printf 'Verified Evolution kernel source %s at %s.\n' "$EVOLUTION_KERNEL_REF" "$actual"
