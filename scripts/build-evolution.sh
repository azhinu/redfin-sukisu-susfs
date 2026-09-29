#!/usr/bin/env bash
set -Eeuo pipefail

[[ $# == 0 ]] || {
  printf 'Unexpected build arguments.\n' >&2
  exit 1
}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
stage=${EVOLUTION_STAGE:-susfs}
case "$stage" in
  plain | sukisu-minimal | sukisu | susfs) ;;
  *)
    printf 'Unsupported Evolution build stage: %s. Use plain, sukisu-minimal, sukisu, or susfs.\n' \
      "$stage" >&2
    exit 1
    ;;
esac

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
cd "$repo_root"

./scripts/prepare-evolution-rom.sh
./scripts/prepare-evolution-kernel.sh "${EVOLUTION_KERNEL_SOURCE:-$repo_root/rom/evolution/kernel}"

export BUILD_TARGET=evolution
export EVOLUTION_STAGE="$stage"
if [[ "$stage" == susfs ]]; then
  export ENABLE_SUSFS=1
else
  export ENABLE_SUSFS=0
fi
export SUKISU_DRIVER_VERSION=${SUKISU_DRIVER_VERSION:-40900}
export JOBS=${JOBS:-3}
export SKIP_MRPROPER=${SKIP_MRPROPER:-0}
export LTO=${LTO:-thin}
export PACKAGE_ARTIFACT_DIR=${PACKAGE_ARTIFACT_DIR:-/workspace/artifacts/evolution-$stage-v420}
if [[ "$stage" == plain ]]; then
  export BUILD_CONFIG=${BUILD_CONFIG:-build.config.redbull.evolution.plain}
elif [[ "$stage" == sukisu-minimal ]]; then
  export BUILD_CONFIG=${BUILD_CONFIG:-build.config.redbull.evolution.sukisu-minimal}
else
  export BUILD_CONFIG=${BUILD_CONFIG:-build.config.redbull.evolution.sukisu}
fi

python3 scripts/sync-stock.py --validate-only
docker compose config --quiet
mkdir -p artifacts
docker compose build stock-build
exec docker compose run --rm stock-build
