from typing import Iterable

import numpy as np
import pandas as pd
import plotly.express as px

REPORT_COLORS = [
    "#6610f2",
    "#dc3545",
    "#ffc107",
    "#198754",
    "#0d6efd",
]


def aggregate_golden_metrics(df: pd.DataFrame, *, group_by: Iterable[str]) -> pd.DataFrame:
    """
    Aggregate golden metrics.
    - throughput_rps, success_rate, saturation → mean across runs
    - p9x_latency_ms is computed using pooled percentile
    """
    records = []
    for keys, sub in df.groupby(list(group_by)):
        # Pool per-run latency arrays into a single 1D array
        latency_arrays = []
        for a in sub["latency_ms"].to_numpy():
            arr = np.asarray(a, dtype=float)
            # Skip zero-dimensional arrays (invalid for pooling) and empty arrays
            if arr.ndim == 0 or arr.size == 0:
                continue
            latency_arrays.append(arr.reshape(-1))

        if not latency_arrays:
            p95 = float("nan")
            p99 = float("nan")
        else:
            pooled = np.concatenate(latency_arrays, dtype=float)
            p95 = float(np.quantile(pooled, 0.95))
            p99 = float(np.quantile(pooled, 0.99))
        agg = {
            **{k: v for k, v in zip(group_by, keys if isinstance(keys, tuple) else (keys,))},
            "throughput_rps": sub["throughput_rps"].mean(),
            "success_rate": sub["success_rate"].mean(),
            "saturation": sub["saturation"].mean(),
            "p95_latency_ms": p95,
            "p99_latency_ms": p99,
        }
        records.append(agg)
    return pd.DataFrame.from_records(records)



def set_data_labels(df: pd.DataFrame, *, column: str) -> list[str]:
    column_order = df[column].unique().tolist()
    df[column] = pd.Categorical(
        df[column], categories=column_order, ordered=True
    )
    return column_order


def make_golden_line_report(df: pd.DataFrame, *, x: str, label: str, html_path: str, intro_html: str) -> None:
    figs = []
    for metric, title, ylabel in [
        ("throughput_rps", "Throughput (req/s)", "Throughput"),
        ("p95_latency_ms", "p95 Latency (ms)", "Latency (ms)"),
        ("success_rate", "Success Rate (%)", "Success Rate"),
        ("saturation", "Worker Saturation", "Utilization"),
    ]:
        fig = px.line(
            df,
            x=x,
            y=metric,
            color="mode",
            markers=True,
            title=title,
            labels={x: label, metric: ylabel},
            color_discrete_sequence=REPORT_COLORS,
        )
        figs.append(fig)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(intro_html)
        for fig in figs:
            f.write(fig.to_html(full_html=False, include_plotlyjs="cdn"))


def make_golden_bar_report(df: pd.DataFrame, *, x: str, label: str, column_order: list[str], html_path: str, intro_html: str) -> None:
    figs = []
    for metric, title, ylabel in [
        ("throughput_rps", "Throughput (req/s)", "Throughput"),
        ("p95_latency_ms", "p95 Latency (ms)", "Latency (ms)"),
        ("success_rate", "Success Rate (%)", "Success Rate"),
        ("saturation", "Worker Saturation", "Utilization"),
    ]:
        fig = px.bar(
            df,
            x=x,
            y=metric,
            color="mode",
            barmode="group",
            title=title,
            labels={x: label, metric: ylabel},
            category_orders={x: column_order},
            color_discrete_sequence=REPORT_COLORS,
        )
        figs.append(fig)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(intro_html)
        for fig in figs:
            f.write(fig.to_html(full_html=False, include_plotlyjs="cdn"))
