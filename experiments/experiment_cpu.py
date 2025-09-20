import pandas as pd

from simweb.entities import ServerMode
from simweb.experiment import run_experiments
from simweb.report import aggregate_golden_metrics, make_golden_line_report


CPU_PERCENTS = [1, 5, 10, 15, 20, 25, 50, 75, 100, 150, 200]

def run_cpu_io_experiments(
) -> pd.DataFrame:
    return run_experiments(
        modes=[ServerMode.sync_mode, ServerMode.async_mode],
        io_means=[200.0],
        cpu_percents=CPU_PERCENTS,
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


def make_html_report(df: pd.DataFrame, html_path: str = "report_cpu.html") -> None:
    intro_html = """
<h1>CPU/IO Experiment Report</h1>
<p>
Exploring impact of CPU cost (relative to IO) on sync vs async.<br>
Golden Metrics shown: Throughput, p95 Latency, Success Rate, Saturation.<br>
Each point = mean across iterations.
</p>
"""
    agg_df = aggregate_golden_metrics(df, group_by=["cpu_io_percent", "mode"])
    make_golden_line_report(
        agg_df,
        x="cpu_io_percent",
        label="CPU Percent of IO",
        html_path=html_path,
        intro_html=intro_html,
    )


if __name__ == "__main__":
    df = run_cpu_io_experiments()
    make_html_report(df)
    print("✅ Saved report_cpu.html")
