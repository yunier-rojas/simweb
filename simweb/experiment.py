import itertools
import sys
import time
from typing import Iterable, TypeVar, Sized, Protocol

import polars as pl
from tqdm import tqdm

from simweb import simulate_server
from simweb.entities import ServerMode, RecordField

T = TypeVar("T")

class SizedIterable(Iterable[T], Sized, Protocol):
    ...


# Reference calibration constants (based on a 100k ms sim run)
SIMULATED_TIME = 100_000  # ms simulated per reference
REAL_TIME = 91.0          # ms real per 100k simulated


def _label_value(value: T | tuple[str, T], cat: str) -> tuple[dict[str, str], T]:
    """If a (label, value) tuple is provided, split it into a label dict and numeric value."""
    if isinstance(value, tuple):
        label, value = value
        return {cat: label}, value
    return {}, value


def _multiple_values(values) -> bool:
    return len(values) > 1


def run_experiments(
        *,
        modes: SizedIterable[ServerMode],
        io_means: SizedIterable[float | tuple[str, float]],
        cpu_percents: SizedIterable[float | tuple[str, float]],
        rates: SizedIterable[float | tuple[str, float]],
        io_limits: SizedIterable[int | tuple[str, int]],
        queue_limits: SizedIterable[int | tuple[str, int]],
        timeouts: SizedIterable[float | tuple[str, float]],
        thread_count: int,
        iterations: int,
        sim_time_ms: float,
        warmup_ms: float,
        seed: int = 42,
) -> pl.DataFrame:
    """
    Run all experiment combinations and return results as a Polars DataFrame.
    - Prints ETA (based on known sim/real ratio).
    - Adds only metadata fields that vary across runs.
    """

    params: dict[RecordField, bool] = {
        RecordField.MODE: _multiple_values(modes),
        RecordField.LABEL_IO: _multiple_values(io_means),
        RecordField.LABEL_CPU: _multiple_values(cpu_percents),
        RecordField.LABEL_RATE: _multiple_values(rates),
        RecordField.LABEL_IO_LIMIT: _multiple_values(io_limits),
        RecordField.LABEL_QUEUE_LIMIT: _multiple_values(queue_limits),
        RecordField.LABEL_TIMEOUT: _multiple_values(timeouts),
    }

    runs = list(itertools.product(
        modes, io_means, cpu_percents, rates, io_limits, queue_limits, timeouts
    ))
    total_runs = len(runs) * iterations

    # --- ETA estimation ---
    total_sim_time_ms = total_runs * (sim_time_ms + warmup_ms)
    eta_time_ms = (total_sim_time_ms / SIMULATED_TIME) * REAL_TIME
    eta_seconds = eta_time_ms / 1000
    eta_minutes, eta_secs = divmod(int(eta_seconds), 60)
    print(f"Estimated ETA: {eta_minutes}m {eta_secs}s for {total_runs} runs")

    start = time.time()
    dfs: list[pl.DataFrame] = []

    with tqdm(total=total_runs, desc="Running experiments", file=sys.stdout) as pbar:
        for (
                mode,
                io_mean_ms,
                cpu_percent,
                rate_rps,
                io_limit,
                queue_limit,
                timeout_ms,
        ) in runs:
            label_io, io_mean_ms = _label_value(io_mean_ms, RecordField.LABEL_IO)
            label_cpu, cpu_percent = _label_value(cpu_percent, RecordField.LABEL_CPU)
            label_rate, rate_rps = _label_value(rate_rps, RecordField.LABEL_RATE)
            label_io_limit, io_limit = _label_value(io_limit, RecordField.LABEL_IO_LIMIT)
            label_queue_limit, queue_limit = _label_value(queue_limit, RecordField.LABEL_QUEUE_LIMIT)
            label_timeout, timeout_ms = _label_value(timeout_ms, RecordField.LABEL_TIMEOUT)

            cpu_mean_ms = io_mean_ms * cpu_percent / 100

            for rep in range(iterations):
                df = simulate_server(
                    mode=mode,
                    cpu_mean_ms=cpu_mean_ms,
                    io_mean_ms=io_mean_ms,
                    rate_rps=rate_rps,
                    io_limit=io_limit,
                    queue_limit=queue_limit,
                    timeout_ms=timeout_ms,
                    thread_count=thread_count,
                    seed=seed,
                    sim_time_ms=sim_time_ms,
                    warmup_ms=warmup_ms,
                )

                # --- Add only varying metadata columns ---
                meta_cols = []
                if params[RecordField.MODE]:
                    meta_cols.append(pl.lit(mode.value).alias(RecordField.MODE))
                if params[RecordField.LABEL_IO]:
                    meta_cols.append(pl.lit(io_mean_ms).alias(RecordField.LABEL_IO))
                if params[RecordField.LABEL_CPU]:
                    meta_cols.append(pl.lit(cpu_percent).alias(RecordField.LABEL_CPU))
                if params[RecordField.LABEL_RATE]:
                    meta_cols.append(pl.lit(rate_rps).alias(RecordField.LABEL_RATE))
                if params[RecordField.LABEL_IO_LIMIT]:
                    meta_cols.append(pl.lit(io_limit).alias(RecordField.LABEL_IO_LIMIT))
                if params[RecordField.LABEL_QUEUE_LIMIT]:
                    meta_cols.append(pl.lit(queue_limit).alias(RecordField.LABEL_QUEUE_LIMIT))
                if params[RecordField.LABEL_TIMEOUT]:
                    meta_cols.append(pl.lit(timeout_ms).alias(RecordField.LABEL_TIMEOUT))

                # --- Always add replication count and thread info ---
                meta_cols.extend([
                    pl.lit(thread_count).alias(RecordField.THREAD_COUNT.value),
                    pl.lit(rep).alias(RecordField.REPLICATION.value),
                ])

                if meta_cols:
                    df = df.with_columns(meta_cols)

                # --- Add any experiment labels (for nice chart names) ---
                for k, v in (
                        label_io | label_cpu | label_rate | label_io_limit | label_timeout
                ).items():
                    df = df.with_columns(pl.lit(v).alias(k))

                dfs.append(df)
                pbar.update(1)

    elapsed = time.time() - start
    real_minutes, real_secs = divmod(int(elapsed), 60)
    print(f"✅ Actual time: {real_minutes}m {real_secs}s "
          f"(~{elapsed/total_runs*1000:.2f} ms per run)")

    return pl.concat(dfs, how="vertical")
