import numpy as np
import pandas as pd
import plotly.express as px

from simweb import simulate_server
from simweb.entities import ServerMode, RequestRecord


def compute_time_series(records: list[RequestRecord], *, bin_ms: float = 1000.0) -> pd.DataFrame:
    """Compute golden metrics over time windows from request records."""
    if not records:
        return pd.DataFrame()

    end_time = max(r.finish_time for r in records)
    bins = np.arange(0, end_time + bin_ms, bin_ms)

    rows = []
    for start, end in zip(bins[:-1], bins[1:]):
        in_bin = [r for r in records if start <= r.finish_time < end]
        if not in_bin:
            continue

        latencies = [r.latency_ms for r in in_bin]
        completed = len(in_bin)  # requests finished in this bin
        throughput = completed / (bin_ms / 1000.0)
        p95 = np.percentile(latencies, 95) if latencies else float("nan")

        # Approximate success rate in bin = completed / arrivals
        arrivals = sum(1 for r in in_bin if r.arrival_time < end)
        success_rate = (completed / arrivals) * 100 if arrivals > 0 else 0.0

        rows.append({
            "time_ms": end,
            "throughput_rps": throughput,
            "p95_latency_ms": p95,
            "success_rate": success_rate,
            # Note: per-bin saturation would need finer-grained counters
        })

    return pd.DataFrame(rows)


def run_dashboard_experiment(
        *,
        mode: ServerMode,
        cpu_mean_ms: float,
        io_mean_ms: float,
        rate_rps: float,
        thread_count: int,
        io_limit: int,
        queue_limit: int,
        timeout_ms: float,
        sim_time_ms: float,
        warmup_ms: float,
        seed: int,
        bin_ms: float = 1000.0,
) -> pd.DataFrame:
    """Run one experiment and return golden metrics as a time series."""

    records, _, _ = simulate_server(
        mode=mode,
        cpu_mean_ms=cpu_mean_ms,
        io_mean_ms=io_mean_ms,
        rate_rps=rate_rps,
        thread_count=thread_count,
        io_limit=io_limit,
        queue_limit=queue_limit,
        timeout_ms=timeout_ms,
        sim_time_ms=sim_time_ms,
        warmup_ms=warmup_ms,
        seed=seed,
    )

    ts_df = compute_time_series(records, bin_ms=bin_ms)
    ts_df["mode"] = mode.value
    return ts_df


def make_dashboard(df: pd.DataFrame, html_path: str = "dashboard.html") -> None:
    """Create interactive dashboard with Plotly line charts over time."""

    figs = []
    for metric, title, ylabel in [
        ("throughput_rps", "Throughput over time", "Throughput (req/s)"),
        ("p95_latency_ms", "p95 Latency over time", "Latency (ms)"),
        ("success_rate", "Success Rate over time", "Success Rate (%)"),
    ]:
        fig = px.line(
            df,
            x="time_ms",
            y=metric,
            color="mode",
            markers=False,
            title=title,
            labels={"time_ms": "Time (ms)", metric: ylabel},
        )
        figs.append(fig)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write("<h1>Golden Metrics Dashboard</h1>")
        for fig in figs:
            f.write(fig.to_html(full_html=False, include_plotlyjs="cdn"))

    print(f"✅ Dashboard saved to {html_path}")


if __name__ == "__main__":

    params = dict(
        cpu_mean_ms=20.0,
        io_mean_ms=200.0,
        rate_rps=100.0,
        io_limit=64,
        queue_limit=64,
        timeout_ms=1000.0,
        sim_time_ms=600_000.0,
        warmup_ms=1000.0,
        seed=42,
    )
    sync_df = run_dashboard_experiment(
        mode=ServerMode.sync_mode,
        thread_count=2,
        **params
    )

    async_df = run_dashboard_experiment(
        mode=ServerMode.async_mode,
        thread_count=1,
        **params,
    )

    all_df = pd.concat([sync_df, async_df], ignore_index=True)
    make_dashboard(all_df)
