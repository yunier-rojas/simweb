# Load testing & metrics with k6

This directory contains a k6-based load test for the Kore `/sim` endpoint. The goal is to compare sync vs async execution models with both client-side and server-side metrics.

## 1. What metrics are collected

- `http_req_duration`: end-to-end client-observed response time. Includes network, queueing, and service time.
- `server_elapsed_ms`: server-reported service time extracted from `X-Sim-Elapsed-Ms` (preferred) or `timing.elapsed_ms` in the JSON body.

Use both metrics together:
- As load increases, queueing expands `http_req_duration` even if `server_elapsed_ms` stays stable.
- `server_elapsed_ms` should align with simulated service time from the server and the discrete-event model.

## 2. One-process / one-core premise

To keep results defensible, pin the server to a single core and keep `workers 1` and `task_threads 1`. Pin the client to a different core to avoid interference.

Server pinning example (Linux):

```bash
taskset -c 2 kore -c conf/kore.conf
```

Client pinning example (Linux):

```bash
taskset -c 3 k6 run loadtest/sim.js
```

## 3. Quickstart

Start server pinned to one core:

```bash
taskset -c 2 ./simweb_sim -c conf/kore.conf -- --max-io-ms 5000 --max-cpu-ms 5000 --max-rt-factor 20 --max-inflight 1000
```

Run k6 pinned to another core:

```bash
taskset -c 3 k6 run \
  -e BASE_URL=http://127.0.0.1:8888 \
  -e MODE=async \
  -e IO_MS=50 \
  -e CPU_MS=10 \
  -e RT_FACTOR=1.0 \
  -e RPS=100 \
  -e DURATION=30s \
  -e PRE_VUS=100 \
  -e MAX_VUS=200 \
  -e OUT_JSON=loadtest/results.json \
  loadtest/sim.js
```

Look at:
- `http_req_duration` percentiles for client latency
- `server_elapsed_ms` percentiles for service time

## 4. Experiment recipes

Pure async, constant arrival rate:

```bash
./loadtest/examples/async-constant.sh
```

Pure sync, constant arrival rate:

```bash
./loadtest/examples/sync-constant.sh
```

Mixed 70/30 async/sync:

```bash
./loadtest/examples/mixed.sh
```

Ramp RPS until saturation:

```bash
k6 run \
  -e EXECUTOR=ramping \
  -e RAMPING_STAGES='[{"target":50,"duration":"30s"},{"target":200,"duration":"60s"},{"target":50,"duration":"30s"}]' \
  -e MODE=async \
  loadtest/sim.js
```

## 5. VU sizing guidance

Arrival-rate executors require enough VUs to sustain the target rate. A rule of thumb:

```
preAllocatedVUs ≥ RPS × expected_iteration_duration_seconds
```

Symptoms of undersizing:
- k6 reports “insufficient VUs”
- achieved RPS is lower than target

## 6. Mapping to the simulator

- Compare `server_elapsed_ms` to simulated service time (CPU + I/O in the model).
- Compare `http_req_duration` to simulated response time if the simulator models queueing and timeouts.
- Do not compare raw RPS without considering queueing and drop behavior.

## 7. Common pitfalls

- Using closed-loop tools and assuming they are open-loop.
- Forgetting to pin the server to a single core.
- Running client and server on the same core.
- Interpreting client latency as service time.

## Environment variables

### Base URL

- `BASE_URL` (default: `http://127.0.0.1:8888`)
- `PATH` (default: `/sim`)

### Load control

- `RPS`
- `DURATION` (e.g. `30s`)
- `PRE_VUS`
- `MAX_VUS`
- `TIMEOUT` (e.g. `2s`)

### Mode selection

- `MODE`: `async` | `sync` | `mix`
- `MIX_ASYNC`: percentage async when `MODE=mix`

### Parameter distributions

Each supports:
- Fixed: `50`, `10`, `1.0`
- Uniform: `uniform:min:max`
- List: `list:v1,v2,v3`
- Weighted list: `wlist:v1:w1,v2:w2,...`

Variables:
- `IO_MS`
- `CPU_MS`
- `RT_FACTOR`

### Reproducibility

- `SEED` (int): RNG seed

### Output

- `OUT_JSON`: write a JSON summary file via `handleSummary()`
- For raw samples, use k6 output options such as `--out json=...`
