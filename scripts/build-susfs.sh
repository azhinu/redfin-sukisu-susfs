#!/usr/bin/env bash
set -Eeuo pipefail

[[ $# == 0 ]] || {
  printf 'Unexpected build arguments.\n' >&2
  exit 1
}

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

command -v docker > /dev/null 2>&1 || {
  printf 'Docker is required.\n' >&2
  exit 1
}
command -v git > /dev/null 2>&1 || {
  printf 'Git is required.\n' >&2
  exit 1
}
docker compose version > /dev/null 2>&1 || {
  printf 'Docker Compose is required.\n' >&2
  exit 1
}

git submodule status --recursive > /dev/null

export ENABLE_SUSFS=1
export SUKISU_DRIVER_VERSION=40900
export JOBS=${JOBS:-3}
export SKIP_MRPROPER=${SKIP_MRPROPER:-0}
export LTO=${LTO:-thin}
export PACKAGE_ARTIFACT_DIR=/workspace/artifacts/susfs-sukisu-v420

python3 scripts/sync-stock.py --validate-only
docker compose config --quiet
mkdir -p artifacts
docker compose build stock-build
exec docker compose run --rm stock-build
