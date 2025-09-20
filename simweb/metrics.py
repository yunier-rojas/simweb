import numpy as np

from simweb.entities import RequestRecord, Metrics, Memory


def compute_metrics(
        records: list[RequestRecord],
        counters: Memory,
        num_threads: int
) -> Metrics:
    steady = [r for r in records if r.arrived_in_steady]
    if not steady:
        return Metrics(
            total_arrivals=counters.arrivals,
            total_completed=counters.completed,
            total_dropped=counters.dropped,
            total_timed_out=counters.timed_out,
            success_rate=0.0,
            latency_ms=np.array([], dtype=float),
            throughput_rps=0.0,
            saturation=0.0,
        )

    latencies = np.array([r.latency_ms for r in steady], dtype=float)
    start_t = min(r.arrival_time for r in steady)
    end_t = max(r.finish_time for r in steady)
    obs_ms = max(end_t - start_t, 0.0)

    throughput_rps = len(steady) / (obs_ms / 1000.0) if obs_ms > 0 else 0.0
    saturation = counters.busy_time / (obs_ms * num_threads)

    return Metrics(
        total_arrivals=counters.arrivals,
        total_completed=counters.completed,
        total_dropped=counters.dropped,
        total_timed_out=counters.timed_out,
        success_rate=(
            counters.completed / counters.arrivals
            if counters.arrivals > 0
            else 0.0
        ) * 100,
        latency_ms=latencies,
        throughput_rps=throughput_rps,
        saturation=saturation,
    )


