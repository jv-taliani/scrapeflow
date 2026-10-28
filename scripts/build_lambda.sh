#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
build="$root/build/lambda"
rm -rf "$build" "$root/build/lambda.zip"
mkdir -p "$build"
python3 -m pip install -q -r "$root/requirements.txt" -t "$build" \
  --platform manylinux2014_x86_64 --python-version 3.12 --implementation cp --only-binary=:all:
cp -r "$root/src/scraper" "$build/"
find "$build" -name "__pycache__" -type d -prune -exec rm -rf {} +
(cd "$build" && zip -qr9 "$root/build/lambda.zip" .)
echo "build/lambda.zip ($(du -h "$root/build/lambda.zip" | cut -f1))"
