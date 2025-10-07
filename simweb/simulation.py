from typing import Any, Protocol, Callable
import simpy
import numpy as np
import polars as pl

from .entities import ServerMode, RequestStatus
from . import samplers


class ServiceFn(Protocol):
    def __call__(
            self,
            *,
            env: simpy.Environment,
            worker_pool: simpy.Resource,
            io_pool: simpy.Resource,
            cpu_pre: float,
            cpu_post: float,
            io_wait: float,
    ) -> Any: ...


# ----------------------------
# Status encoding
# ----------------------------
STATUS_MAP = {
    RequestStatus.completed: 0,
    RequestStatus.timeout: 1,
    RequestStatus.dropped: 2,
}


# ----------------------------
# Service types
# ----------------------------

def _sync_service(
        *,
        env: simpy.Environment,
        worker_pool: simpy.Resource,
        io_pool: simpy.Resource,
        cpu_pre: float,
        cpu_post: float,
        io_wait: float,
) -> float:
    """Return total CPU time used by this request."""
    cpu_time = 0.0
    with worker_pool.request() as req:
        yield req
        # CPU before I/O
        if cpu_pre > 0:
            cpu_time += cpu_pre
            yield env.timeout(cpu_pre)

        # I/O (thread is blocked!)
        if io_wait > 0:
            with io_pool.request() as io_req:
                yield io_req
                yield env.timeout(io_wait)

        # CPU after I/O
        if cpu_post > 0:
            cpu_time += cpu_post
            yield env.timeout(cpu_post)

    return cpu_time


def _async_service(
        *,
        env: simpy.Environment,
        worker_pool: simpy.Resource,
        io_pool: simpy.Resource,
        cpu_pre: float,
        cpu_post: float,
        io_wait: float,
) -> float:
    """Return total CPU time used by this request."""
    cpu_time = 0.0

    # CPU before I/O
    if cpu_pre > 0:
        with worker_pool.request() as req1:
            yield req1
            cpu_time += cpu_pre
            yield env.timeout(cpu_pre)

    # I/O (thread released!)
    if io_wait > 0:
        with io_pool.request() as io_req:
            yield io_req
            yield env.timeout(io_wait)

    # CPU after I/O
    if cpu_post > 0:
        with worker_pool.request() as req2:
            yield req2
            cpu_time += cpu_post
            yield env.timeout(cpu_post)

    return cpu_time


# ----------------------------
# Request process
# ----------------------------

def _request_process(
        *,
        env: simpy.Environment,
        service_fn: ServiceFn,
        req_id: int,
        worker_pool: simpy.Resource,
        io_pool: simpy.Resource,
        cpu_times: Callable[[], float],
        io_times: Callable[[], float],
        warmup_ms: float,
        timeout_limit: float,
        rng: np.random.Generator,
        # column stores
        req_ids, arrivals, finishes, latencies, statuses,
) -> Any:
    arrival_time = env.now
    recorded = False

    def service() -> Any:
        nonlocal recorded
        total_cpu = cpu_times()
        split = rng.random()
        cpu_pre = total_cpu * split
        cpu_post = total_cpu * (1 - split)
        io_wait = io_times()

        try:
            _ = yield from service_fn(
                env=env,
                worker_pool=worker_pool,
                io_pool=io_pool,
                cpu_pre=cpu_pre,
                cpu_post=cpu_post,
                io_wait=io_wait,
            )
            status = RequestStatus.completed
        except simpy.Interrupt:
            # Timeout happened mid-service
            _ = 0.0
            status = RequestStatus.timeout

        finish_time = env.now
        if arrival_time >= warmup_ms and not recorded:
            req_ids.append(req_id)
            arrivals.append(arrival_time)
            finishes.append(finish_time)
            latencies.append(finish_time - arrival_time)
            statuses.append(STATUS_MAP[status])
            recorded = True

    svc_proc = env.process(service())
    if timeout_limit > 0:
        timeout_evt = env.timeout(timeout_limit)
        result = yield svc_proc | timeout_evt
        if timeout_evt in result and not recorded:
            finish_time = env.now
            if arrival_time >= warmup_ms:
                req_ids.append(req_id)
                arrivals.append(arrival_time)
                finishes.append(finish_time)
                latencies.append(timeout_limit)
                statuses.append(STATUS_MAP[RequestStatus.timeout])
            try:
                svc_proc.interrupt("timeout")
            except RuntimeError:
                pass
            recorded = True
    else:
        yield svc_proc


# ----------------------------
# Arrival process
# ----------------------------

def _arrival_process(
        *,
        env: simpy.Environment,
        worker_pool: simpy.Resource,
        io_pool: simpy.Resource,
        service_fn: ServiceFn,
        rng: np.random.Generator,
        cpu_times: Callable[[], float],
        io_times: Callable[[], float],
        arrival_times: Callable[[], float],
        warmup_ms: float,
        max_in_system: int,
        timeout_ms: float,
        # column stores
        req_ids, arrivals, finishes, latencies, statuses,
) -> Any:
    req_id = 0
    in_system = 0

    while True:
        arrival = arrival_times()
        yield env.timeout(arrival)

        if in_system >= max_in_system:
            # Request is dropped
            req_id += 1
            now = env.now
            req_ids.append(req_id)
            arrivals.append(now)
            finishes.append(now)
            latencies.append(0.0)
            statuses.append(STATUS_MAP[RequestStatus.dropped])
            continue

        req_id += 1
        in_system += 1

        def wrap_request():
            nonlocal in_system
            yield from _request_process(
                env=env,
                req_id=req_id,
                service_fn=service_fn,
                worker_pool=worker_pool,
                io_pool=io_pool,
                cpu_times=cpu_times,
                io_times=io_times,
                warmup_ms=warmup_ms,
                timeout_limit=timeout_ms,
                rng=rng,
                req_ids=req_ids,
                arrivals=arrivals,
                finishes=finishes,
                latencies=latencies,
                statuses=statuses,
            )
            in_system -= 1

        env.process(wrap_request())


# ----------------------------
# Simulation entrypoint
# ----------------------------

def simulate_server(
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
        cpu_dist: str = "exponential",
        io_dist: str = "exponential",
        cpu_lognorm_sigma: float = 1.0,
        io_lognorm_sigma: float = 1.0,
        arrival_dist: str = "poisson",
        burst_factor: float = 5.0,
        burst_prob: float = 0.1,
) -> pl.DataFrame:
    env = simpy.Environment()

    # column stores
    req_ids, arrivals, finishes, latencies, statuses = ([] for _ in range(5))

    is_async = mode is ServerMode.async_mode
    num_threads = 1 if is_async else thread_count
    service_fn = _async_service if is_async else _sync_service
    worker_pool = simpy.Resource(env, capacity=num_threads)
    io_pool = simpy.Resource(env, capacity=io_limit)
    max_in_system = num_threads + queue_limit
    rng = np.random.default_rng(seed)

    # Samplers
    cpu_func = getattr(samplers, f"time_{cpu_dist}")
    cpu_times = cpu_func(rng=rng, mean_ms=cpu_mean_ms, sigma=cpu_lognorm_sigma)

    io_func = getattr(samplers, f"time_{io_dist}")
    io_times = io_func(rng=rng, mean_ms=io_mean_ms, sigma=io_lognorm_sigma)

    arr_func = getattr(samplers, f"arrival_{arrival_dist}")
    arrival_times = arr_func(
        rng=rng, rate_rps=rate_rps, burst_factor=burst_factor, burst_prob=burst_prob
    )

    env.process(
        _arrival_process(
            env=env,
            worker_pool=worker_pool,
            io_pool=io_pool,
            service_fn=service_fn,
            cpu_times=cpu_times,
            io_times=io_times,
            arrival_times=arrival_times,
            rng=rng,
            warmup_ms=warmup_ms,
            timeout_ms=timeout_ms,
            req_ids=req_ids,
            arrivals=arrivals,
            finishes=finishes,
            latencies=latencies,
            statuses=statuses,
            max_in_system=max_in_system,
        )
    )
    env.run(until=sim_time_ms)

    # Build Polars DataFrame
    return pl.DataFrame(
        {
            "req_id": req_ids,
            "arrival_time": arrivals,
            "finish_time": finishes,
            "latency_ms": latencies,
            "status": statuses,   # 0=completed, 1=timeout, 2=dropped
        }
    )
