import pandas as pd

from simweb.entities import ServerMode
from simweb.experiment import run_experiments
from simweb.report import aggregate_golden_metrics, make_golden_bar_report

# From https://github.com/jabbalaci/SpeedTests
RUNTIMES = {
    "Rust": 1.10,
    "Java": 1.87,
    "C#": 1.91,
    "JavaScript": 2.55,
    "CPython": 117.3,
}

BASE_CPU_MEAN_MS = 10.0


def run_runtime_experiments() -> pd.DataFrame:
    return run_experiments(
        modes=[ServerMode.sync_mode, ServerMode.async_mode],
        io_means=[200.0],
        cpu_percents=[(l, BASE_CPU_MEAN_MS * v / 200.0 * 100) for l, v in RUNTIMES.items()],
        rates=[100.0],
        io_limits=[64],
        queue_limits=[64],
        timeouts=[1000.0],
        thread_count=2,
        iterations=100,
        sim_time_ms=60_000.0,
        warmup_ms=1000.0,
        seed=42,
    )


def make_html_report(df: pd.DataFrame, html_path: str = "report_runtime.html") -> None:
    intro_html = """
<h1>Runtime Experiment Report</h1>
<p>
Comparing runtimes (C baseline) across sync (thread pool) and async (event loop) models.<br>
Golden Metrics shown: Throughput, p95 Latency, Success Rate, Saturation.<br>
Each bar = mean across iterations.
</p>
"""
    agg_df = aggregate_golden_metrics(df, group_by=["label_cpu", "mode"])

    runtime_order = df["label_cpu"].unique().tolist()
    make_golden_bar_report(
        agg_df,
        x="label_cpu",
        label="Runtime",
        column_order=runtime_order,
        html_path=html_path,
        intro_html=intro_html,
    )


if __name__ == "__main__":
    df = run_runtime_experiments()
    make_html_report(df)
    print("✅ Saved report_runtime.html")
