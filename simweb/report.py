from typing import Any
import polars as pl
import plotly.express as px
from plotly.graph_objs import Figure


from simweb.entities import RecordField


def generate_time_charts(
    df: pl.DataFrame,
    layout: dict[str, dict[str, Any]] | None = None,
    traces: dict[str, dict[str, Any]] | None = None,
) -> list[Figure]:

    df = df.with_columns(
        (pl.col("success_rate") * 100)
    )

    start_time = df["time_ms"].min()
    end_time = df["time_ms"].max()

    total_minutes = int((end_time - start_time) / 60_000)

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
            labels={"time_ms": "Time (ms)", metric: ylabel, "mode": "Mode"},
        )

        fig.update_xaxes(
            tickvals=[m * 60_000 for m in range(total_minutes + 1)],
            ticktext=[str(m) for m in range(total_minutes + 1)],
            title="Time (minutes)",
        )

        if traces:
            fig.update_traces(**traces)

        if layout:
            fig.update_layout(**layout)

        figs.append(fig)

    return figs


def generate_line_charts(
    df: pl.DataFrame,
    *,
    x: str,
    label: str,
    layout: dict[str, dict[str, Any]] | None = None,
    traces: dict[str, dict[str, Any]] | None = None,
) -> list[Figure]:
    df = df.with_columns(
        (pl.col("success_rate") * 100)
    )

    figs = []
    for metric, title, ylabel in [
        ("throughput_rps", "Throughput (req/s)", "Throughput"),
        ("p95_latency_ms", "p95 Latency (ms)", "Latency (ms)"),
        ("success_rate", "Success Rate (%)", "Success Rate"),
    ]:
        fig = px.line(
            df,
            x=x,
            y=metric,
            color="mode",
            markers=True,
            title=title,
            labels={x: label, metric: ylabel},
            color_discrete_sequence=px.colors.qualitative.Plotly,
        )
        figs.append(fig)
        if traces:
            fig.update_traces(**traces)

        if layout:
            fig.update_layout(**layout)

    return figs


def generate_bar_charts(
    df: pl.DataFrame,
    *,
    x: str,
    label: str,
    column_order: list[str],
    layout: dict[str, dict[str, Any]] | None = None,
    traces: dict[str, dict[str, Any]] | None = None,
) -> list[Figure]:
    df = df.with_columns(
        (pl.col("success_rate") * 100)
    )

    figs = []
    for metric, title, ylabel in [
        ("throughput_rps", "Throughput (req/s)", "Throughput"),
        ("p95_latency_ms", "p95 Latency (ms)", "Latency (ms)"),
        ("success_rate", "Success Rate (%)", "Success Rate"),
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
            color_discrete_sequence=px.colors.qualitative.Plotly,
        )
        if traces:
            fig.update_traces(**traces)

        if layout:
            fig.update_layout(**layout)

        figs.append(fig)

    return figs


def generate_heatmap_charts(
    df: pl.DataFrame,
    *,
    x: str,
    x_label: str,
    y: str,
    y_label: str,
    title: str,
    facet: RecordField | None = None,
    layout: dict[str, dict[str, Any]] | None = None,
    traces: dict[str, dict[str, Any]] | None = None,
    colors: str = "plotly3"
) -> list[Figure]:

    df = df.with_columns(
        (pl.col("success_rate") * 100)
    )

    figs = []
    for metric, sub_title, ylabel, color in [
        ("throughput_rps", "Throughput (req/s)", "Throughput", colors),
        ("p95_latency_ms", "p95 Latency (ms)", "Latency (ms)", f"{colors}_r"),
        ("success_rate", "Success Rate (%)", "Success Rate", colors),
    ]:


        fig = px.density_heatmap(
            df,
            x=x,
            y=y,
            z=metric,
            facet_col=facet,
            facet_col_wrap=2 if facet else 0,
            histfunc="avg",
            title=f"{title}: {sub_title}",
            labels={x: x_label, y: y_label, metric: ylabel},
            color_continuous_scale=color,
        )

        if traces:
            fig.update_traces(**traces)

        if layout:
            fig.update_layout(**layout)
        figs.append(fig)

    return figs
