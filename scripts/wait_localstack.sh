#!/usr/bin/env bash
set -euo pipefail
url="${AWS_ENDPOINT_URL:-http://localhost:4566}/_localstack/health"
for _ in $(seq 1 60); do
  if curl -sf "$url" >/dev/null; then
    echo "LocalStack pronto"
    exit 0
  fi
  sleep 2
done
echo "LocalStack não respondeu em $url" >&2
exit 1
