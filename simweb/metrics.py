from typing import Iterable
import polars as pl

from simweb.entities import RecordField

STATUS_COMPLETED = 0


def compute_group_metrics(
        df: pl.DataFrame,
        *,
        group_by: Iterable[str],
) -> pl.DataFrame:

    per_rep = (
        df.group_by(list(group_by) + ["replication"])
        .agg([
            # Number of completed requests
            (pl.col("status") == 0).sum().alias("completed_reqs"),

            # Success rate: completed / total
            ((pl.col("status") == 0).mean()).alias("success_rate"),

            # Latency percentiles among completed only
            pl.col("latency_ms")
            .filter(pl.col("status") == 0)
            .quantile(0.95, "nearest")
            .alias("p95_latency_ms"),
            pl.col("latency_ms")
            .filter(pl.col("status") == 0)
            .quantile(0.99, "nearest")
            .alias("p99_latency_ms"),

            # Duration of this replication (in seconds)
            ((pl.col("finish_time").max() - pl.col("arrival_time").min()) / 1000)
            .alias("duration_s"),
        ])
        # Compute throughput = completed requests / duration
        .with_columns(
            (pl.col("completed_reqs") / pl.col("duration_s")).alias("throughput_rps")
        )
    )

    agg = (
        per_rep.group_by(group_by)
        .agg([
            pl.mean("throughput_rps"),
            pl.mean("success_rate"),
            pl.mean("p95_latency_ms"),
            pl.mean("p99_latency_ms"),
        ])
    )

    return agg.sort(group_by)

def compute_time_metrics(
        df: pl.DataFrame,
        *,
        group_by: Iterable[str],
        bin_ms: float = 1000.0,
) -> pl.DataFrame:

    # --- Assign each request to a time bin based on its finish time
    df = df.with_columns(
        ((pl.col("finish_time") // bin_ms) * bin_ms)
        .alias("time_ms")
    )

    agg = (
        df.group_by(list(group_by) + ["time_ms"])
        .agg([
            # Total completed requests
            (pl.col("status") == 0).sum().alias("completed_reqs"),

            # Success rate
            ((pl.col("status") == 0).mean()).alias("success_rate"),

            # Latency percentiles (only completed)
            pl.col("latency_ms")
            .filter(pl.col("status") == 0)
            .quantile(0.95, "nearest")
            .alias("p95_latency_ms"),
            pl.col("latency_ms")
            .filter(pl.col("status") == 0)
            .quantile(0.99, "nearest")
            .alias("p99_latency_ms"),
        ])
        # Throughput = completed requests / bin duration (in seconds)
        .with_columns(
            (pl.col("completed_reqs") / (bin_ms / 1000)).alias("throughput_rps")
        )
        .select(
            list(group_by)
            + ["time_ms", "throughput_rps", "success_rate",
               "p95_latency_ms", "p99_latency_ms"]
        )
        .sort(["time_ms"])
    )

    return agg