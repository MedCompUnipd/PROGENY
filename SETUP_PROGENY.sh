#!/usr/bin/env bash
# Guided setup for scientists: no JSON, YAML, Git operation or manual build.
set -Eeuo pipefail
cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
if ! command -v pixi >/dev/null 2>&1; then
    echo "Pixi is required. Installation instructions: https://pixi.sh/" >&2
    exit 2
fi
if [[ ! -t 0 ]]; then
    echo "Run this assistant in an interactive terminal (not a pipe)." >&2
    exit 2
fi
printf '\nPreparing the PROGENY environment...\n'
pixi install --locked
pixi run python scripts/installation/progeny_setup.py
