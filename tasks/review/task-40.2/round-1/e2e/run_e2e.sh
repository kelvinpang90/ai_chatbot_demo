#!/usr/bin/env bash
# Reviewer's e2e harness for task 40.2. Backend mounted read-only.
set -u
export MSYS_NO_PATHCONV=1
BACKEND=$(cygpath -w "$1")
E2E=$(cygpath -w "$(cd "$(dirname "$0")" && pwd)")
NET=rv402e2e
docker network create $NET >/dev/null 2>&1
docker run -d --rm --name rv402redis --network $NET --network-alias redis redis:7-alpine redis-server --databases 32 >/dev/null
docker run --rm --network $NET -v "$BACKEND:/app:ro" -v "$E2E:/e2e:ro" -w /app \
  -e PYTHONPATH=/app -e PYTHONIOENCODING=utf-8 -e PYTHONDONTWRITEBYTECODE=1 python:3.13-slim \
  sh -c "pip install -q -r requirements.txt >/dev/null 2>&1 && python /e2e/${2:-e2e_wiring.py}"
docker stop rv402redis >/dev/null
docker network rm $NET >/dev/null
