# SimWeb: Sync vs Async Server Simulation

This project provides a **discrete-event simulation framework** (built with [SimPy](https://simpy.readthedocs.io)) to explore the performance trade-offs between **synchronous** and **asynchronous** web server workers.

The framework’s purpose is to act as a **sandbox for optimizing golden metrics** — throughput, latency, saturation, and success rate — under different workload and server configurations.

Instead of relying on ad-hoc benchmarks, you can systematically vary parameters (CPU cost, I/O wait, arrival rate, concurrency limits, backlog size, timeouts) and see how sync and async patterns perform.

---

## Core Idea

We simulate a **web worker process** that handles requests.

Each request may:

- Spend some **CPU time**.
- Spend some **I/O wait time**.

The server can operate in two modes:

- **Sync**: multiple worker threads; each thread blocks while doing I/O.
- **Async**: a single thread that can release itself during I/O, resuming later.

By running controlled experiments, you can ask optimization questions such as:
- What thread count minimizes latency without wasting CPU?
- At what CPU/I/O ratio does async outperform sync in throughput?
- How much backlog and I/O concurrency is needed to maximize success rate under bursty arrivals?
- Which golden metric (throughput, latency, saturation, success rate) is most sensitive to each parameter?

---

## Project Structure

- `simulation.py` – Implements the server model with SimPy (sync vs async services, request and arrival processes).
- `metrics.py` – Computes golden metrics (throughput, p95 latency, success rate, saturation).
- `experiment.py` – Runs parameter sweeps (CPU%, I/O mean, arrival rates, thread counts, queue limits, etc.) and collects results.
- `report.py` – Generates Plotly HTML reports for visualizing golden metrics.
- `entities.py` – Contains dataclasses (`Metrics`, `RequestRecord`, `Memory`, `ServerMode`) that define simulation state.

---

## Golden Metrics

For each experiment we compute:

- **Throughput (req/s)** – steady-state completed requests per second.
- **p95 latency (ms)** – 95th percentile response time.
- **Success rate (%)** – fraction of requests that were completed (vs dropped or timed out).
- **Saturation** – fraction of worker time spent actively processing CPU.

---

## Assumptions

- **One worker process per CPU core** (best practice).
- **Sync servers**: typically 2–4 threads per process.
- **Async servers**: usually 1 event loop per process.
- **Arrival process**: by default Poisson (exponential interarrival). Bursty arrivals can be modeled as an option.
- **Service times**: exponential by default (memoryless), with optional log-normal (heavy-tailed) distributions.
- **I/O wait**: modeled as a resource pool (`io_pool`) to simulate finite external concurrency.
- **Queueing**: limited backlog (`queue_limit`), beyond which requests are dropped.

---

## Limitations

- **No context-switch overheads**: Thread scheduling and async event-loop costs are ignored.
- **No kernel-level detail**: We abstract away actual socket, disk, or DB behavior; “I/O” is just simulated wait.
- **Percentile aggregation**: By default, per-replication p95s are averaged. If raw latencies are available, pooled percentiles can be computed for accuracy.
- **Timeout handling**: Timeouts interrupt running requests, but correctness depends on SimPy releasing resources cleanly. Stress testing is needed to confirm no leaks.
- **CPU model**: CPU times are sampled randomly (exponential/lognormal) but not tied to real instruction counts or language runtimes.
- **Async model**: Assumes perfect non-blocking I/O and ignores accidental blocking calls.
- **Scaling**: Only models a single worker process. In production, deployments scale across many processes and machines.

---

## Why Simulate?

From an SRE perspective:
- Async is not *always* faster — it depends on the **ratio of CPU to I/O**.
- Simulations help expose regimes where:
    - Sync outperforms async (CPU-heavy).
    - Async shines (I/O-heavy, high concurrency).
    - Both degrade (queues fill, timeouts explode).

From a Simulation perspective:
- Exponential distributions make results comparable to queueing theory.
- Log-normal distributions introduce realistic tail behavior.
- Bursty arrivals simulate flash crowds and traffic spikes.

---

## Example Usage

Run experiments:

```python
from simweb.experiment import run_experiments
from simweb.report import make_golden_line_report

df = run_experiments(
    modes=[ServerMode.sync_mode, ServerMode.async_mode],
    io_means=[200.0],
    cpu_percents=[(l, v) for l, v in [(10, 10.0), (50, 50.0)]],
    rates=[100.0],
    io_limits=[64],
    queue_limits=[64],
    timeouts=[1000.0],
    thread_count=4,
    iterations=10,
    sim_time_ms=6000.0,
    warmup_ms=1000.0,
)

make_golden_line_report(
    df,
    x="cpu_io_percent",
    label="CPU % of IO",
    html_path="report.html",
    intro_html="<h1>CPU vs IO Experiment</h1>"
)
