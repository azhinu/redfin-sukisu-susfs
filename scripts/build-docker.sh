#!/usr/bin/env bash
set -Eeuo pipefail

[[ $# == 0 ]] || {
  printf 'Unexpected build arguments.\n' >&2
  exit 1
}
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p artifacts
docker compose build stock-build
docker compose run --rm stock-build
