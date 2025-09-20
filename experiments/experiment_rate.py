import pandas as pd

from simweb.entities import ServerMode
from simweb.experiment import run_experiments
from simweb.report import aggregate_golden_metrics, make_golden_line_report


ARRIVAL_RATES = [1, 5, 10, 20, 50, 100, 200]  # req/s

def run_rate_experiments(
) -> pd.DataFrame:
    return run_experiments(
        modes=[ServerMode.sync_mode, ServerMode.async_mode],
        io_means=[200.0],
        cpu_percents=[10],
        rates=ARRIVAL_RATES,
        io_limits=[64],
        queue_limits=[64],
        timeouts=[1000.0],
        thread_count=2,
        iterations=100,
        sim_time_ms=60_000.0,
        warmup_ms=1000.0,
        seed=42,
    )


def make_html_report(df: pd.DataFrame, html_path: str = "report_rate.html") -> None:
    intro_html = """
<h1>Rate Experiment Report</h1>
<p>
Exploring impact of increasing arrival rate (req/s) on sync vs async.<br>
Golden Metrics shown: Throughput, p95 Latency, Success Rate, Saturation.<br>
Each point = mean across iterations.
</p>
"""
    agg_df = aggregate_golden_metrics(df, group_by=["arrival_rate_rps", "mode"])
    make_golden_line_report(
        agg_df,
        x="arrival_rate_rps",
        label="Req/s",
        html_path=html_path,
        intro_html=intro_html,
    )


if __name__ == "__main__":
    df = run_rate_experiments()
    make_html_report(df)
    print("✅ Saved report_rate.html")
