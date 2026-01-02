# Kore Sync/Async Simulation Server

This Kore application exposes a single endpoint that simulates sync vs async request handling with configurable CPU and I/O delays.

## Build

This app expects a Kore installation and uses the Kore build Makefile. Make sure Kore was built with `TASKS=1` support.

```bash
cd kore_sim
make TASKS=1 KORE_PATH=/path/to/kore/install
```

Alternatively, with `kodev`:

```bash
kodev run -- --max-io-ms 5000 --max-cpu-ms 5000 --max-rt-factor 20 --max-inflight 1000
```

## Run

```bash
./simweb_sim -c conf/kore.conf -- \
  --max-io-ms 5000 \
  --max-cpu-ms 5000 \
  --max-rt-factor 20.0 \
  --max-total-ms 8000 \
  --max-inflight 1000 \
  --default-mode async \
  --json-pretty 1
```

## Running on one core (one process, one core)

This server is intended to validate sync vs async execution models under a single-core constraint. To make the claim “one process, one core” defensible, you must configure Kore for one worker and one task thread and pin the process to a single CPU core at the OS/container level.

### Kore configuration (required)

Add these directives to `conf/kore.conf` and keep them at 1:

```conf
workers 1
task_threads 1
```

Why this matters:
- `workers 1` ensures a single Kore worker process handles all requests.
- `task_threads 1` ensures sync mode uses a single task thread.
- Async handlers still execute on the worker event loop; sync mode uses tasks but should remain on the same core once pinned.

### Local execution (Linux)

Pin the process to a single core. This is required even with `workers 1`, because the OS scheduler can still move the process across cores without affinity.

Using `kore` directly:

```bash
taskset -c 2 kore -c conf/kore.conf
```

Using `kodev run`:

```bash
taskset -c 2 kodev run -- --max-io-ms 5000 --max-cpu-ms 5000 --max-rt-factor 20 --max-inflight 1000
```

Affinity applies to both the worker and task threads; they will all run on the pinned core.

### Local execution (macOS)

macOS does not provide strict per-core pinning. You can only apply best-effort policies, and results are not strictly comparable to Linux.

Best-effort example:

```bash
sudo taskpolicy -c 1 kore -c conf/kore.conf
```

Do not treat macOS results as equivalent to Linux single-core measurements.

### Docker / container execution (recommended)

Containers provide more reliable core isolation than a shared development machine.

```bash
docker run --rm -it \
  --cpuset-cpus="2" \
  --cpus="1.0" \
  -p 8888:8888 \
  -v "$PWD:/app" \
  -w /app/kore_sim \
  kore:latest \
  ./simweb_sim -c conf/kore.conf -- --max-io-ms 5000 --max-cpu-ms 5000 --max-rt-factor 20 --max-inflight 1000
```

Notes:
- `--cpuset-cpus="2"` pins the container to core 2.
- `--cpus="1.0"` limits CPU time but does not pin to a specific core; it is not a substitute for `--cpuset-cpus`.

### systemd (optional but recommended)

Minimal service configuration:

```ini
[Service]
ExecStart=/path/to/simweb_sim -c /path/to/conf/kore.conf -- --max-io-ms 5000 --max-cpu-ms 5000 --max-rt-factor 20 --max-inflight 1000
CPUAffinity=2
TasksMax=1
CPUQuota=100%
```

Notes:
- `CPUAffinity=2` pins the service to core 2.
- `CPUQuota=100%` limits CPU usage but does not enforce core affinity.
- `TasksMax=1` is optional and limits the number of tasks, not CPU cores.

### Verification steps (mandatory)

Confirm CPU affinity and active processor:

```bash
taskset -cp <pid>
```

Correct output includes a single core, for example: `pid 12345's current affinity list: 2`.

```bash
ps -o pid,psr,comm -p <pid>
```

The `psr` column should consistently show the pinned core.

Optional:

```bash
grep Cpus_allowed_list /proc/<pid>/status
```

Correct output lists a single core, e.g. `Cpus_allowed_list: 2`.

### Guarantees and non-guarantees

Guaranteed:
- Single Kore worker process.
- All request execution confined to one CPU core when affinity is set.
- Deterministic comparison of sync vs async scheduling under a single-core constraint.

Not guaranteed:
- No kernel interrupts or background scheduler effects.
- Cycle-level determinism.
- Identical behavior across operating systems.

### Common mistakes

- Relying on `workers 1` without `taskset` or CPU affinity.
- Running multiple task threads.
- Assuming macOS provides strict core pinning.
- Benchmarking while other processes share the same core.
- Confusing `CPUQuota` with CPU affinity.

## Endpoint

```
GET /sim?mode=async|sync&io_ms=50&cpu_ms=10&rt_factor=1.0
```

### Parameters

- `mode`: `sync` or `async` (defaults to `--default-mode`).
- `io_ms`: simulated I/O delay in milliseconds.
- `cpu_ms`: simulated CPU busy time in milliseconds.
- `rt_factor`: runtime factor (multiplier applied to `cpu_ms` only).

### CLI limits

- `--max-io-ms`
- `--max-cpu-ms`
- `--max-rt-factor`
- `--max-total-ms`
- `--max-inflight`
- `--max-cpu-spin-ms` (caps async CPU slice size in ms)
- `--default-mode`
- `--json-pretty`

## Examples

Async request:

```bash
curl -s "http://127.0.0.1:8888/sim?mode=async&io_ms=50&cpu_ms=10&rt_factor=1.0"
```

Sync request:

```bash
curl -s "http://127.0.0.1:8888/sim?mode=sync&io_ms=100&cpu_ms=25&rt_factor=1.5"
```

Inflight cap (expect 429 JSON):

```bash
curl -s "http://127.0.0.1:8888/sim?mode=async&io_ms=1&cpu_ms=1&rt_factor=1.0"
```

## Minimal test plan

- Send both sync and async requests with different params and verify JSON output.
- Use a load tool (e.g., `hey` or `wrk`) to generate concurrent requests with mixed modes.
- Set `--max-inflight 1` and verify a second concurrent request returns 429.
