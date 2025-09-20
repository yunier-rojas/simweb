import itertools
from dataclasses import asdict
from typing import Iterable, TypeVar

import pandas as pd

from simweb import simulate_server
from simweb.entities import ServerMode
from simweb.metrics import compute_metrics

T = TypeVar('T')

def _label_value(value: T | tuple[str, T], cat: str) -> tuple[dict[str, str], T]:
    if isinstance(value, tuple):
        label, value = value
        return {cat: label}, value
    return {}, value



def run_experiments(
        *,
        modes: Iterable[ServerMode],
        io_means: Iterable[float | tuple[str, float]],
        cpu_percents: Iterable[float | tuple[str, float]],
        rates: Iterable[float | tuple[str, float]],
        io_limits: Iterable[int | tuple[str, int]],
        queue_limits: Iterable[int | tuple[str, int]],
        timeouts: Iterable[float | tuple[str, float]],
        thread_count: int,
        iterations: int,
        sim_time_ms: float,
        warmup_ms: float,
        seed: int = 42,
) -> pd.DataFrame:

    records: list[dict] = []


    for mode, io_mean_ms, cpu_percent, rate_rps, io_limit, queue_limit, timeout_ms in itertools.product(
            modes, io_means, cpu_percents, rates, io_limits, queue_limits, timeouts
    ):
        label_io, io_mean_ms = _label_value(io_mean_ms, "label_io")
        label_cpu, cpu_percent = _label_value(cpu_percent, "label_cpu")
        label_rate, rate_rps = _label_value(rate_rps, "label_rate")
        label_io_limit, io_limit = _label_value(io_limit, "label_io_limit")
        label_queue_limit, queue_limit = _label_value(queue_limit, "label_queue_limit")
        label_timeout, timeout_ms = _label_value(timeout_ms, "label_timeout")
        cpu_mean_ms = io_mean_ms * cpu_percent / 100
        for rep in range(iterations):
            recs, memory, threads = simulate_server(
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
            metrics = compute_metrics(recs, memory, threads)
            info = asdict(metrics)
            records.append(
                {
                    **info,
                    **(label_io | label_cpu | label_rate | label_io_limit | label_timeout),
                    "cpu_io_percent": cpu_percent,
                    "cpu_mean_ms": cpu_mean_ms,
                    "io_mean_ms": io_mean_ms,
                    "arrival_rate_rps": rate_rps,
                    "thread_count": thread_count,
                    "io_limit": io_limit,
                    "queue_limit": queue_limit,
                    "timeout_ms": timeout_ms,
                    "mode": mode.value,
                    "replication": rep,
                    "success_rate": metrics.success_rate,
                }
            )

    return pd.DataFrame.from_records(records)

