#!/usr/bin/env bash
set -euo pipefail

k6 run \
  -e BASE_URL=http://127.0.0.1:8888 \
  -e MODE=sync \
  -e IO_MS=50 \
  -e CPU_MS=10 \
  -e RT_FACTOR=1.0 \
  -e RPS=100 \
  -e DURATION=30s \
  -e PRE_VUS=100 \
  -e MAX_VUS=200 \
  -e OUT_JSON=loadtest/sync-constant.json \
  loadtest/sim.js
