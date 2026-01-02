#!/usr/bin/env bash
set -euo pipefail

k6 run \
  -e BASE_URL=http://127.0.0.1:8888 \
  -e MODE=mix \
  -e MIX_ASYNC=70 \
  -e IO_MS=uniform:10:50 \
  -e CPU_MS=uniform:5:20 \
  -e RT_FACTOR=1.0 \
  -e RPS=100 \
  -e DURATION=30s \
  -e PRE_VUS=100 \
  -e MAX_VUS=200 \
  -e OUT_JSON=loadtest/mixed.json \
  loadtest/sim.js
