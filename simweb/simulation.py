from typing import Any, Protocol, Callable
import simpy
import numpy as np

from .entities import Memory, ServerMode
from .metrics import RequestRecord
from . import samplers

class ServiceFn(Protocol):
    def __call__(
            self,
            *,
            env: simpy.Environment,
            worker_pool: simpy.Resource,
            io_pool: simpy.Resource,
            counters: Memory,
            cpu_pre: float,
            cpu_post: float,
            io_wait: float,
    ) -> Any:
        ...

# ----------------------------
# Service types
# ----------------------------

def _sync_service(
        *,
        env: simpy.Environment,
        worker_pool: simpy.Resource,
        io_pool: simpy.Resource,
        counters: Memory,
        cpu_pre: float,
        cpu_post: float,
        io_wait: float,
):
    total_hold = 0.0
    with worker_pool.request() as req:
        yield req
        # CPU before I/O
        if cpu_pre > 0:
            counters.busy_time += cpu_pre
            total_hold += cpu_pre
            yield env.timeout(cpu_pre)

        # I/O (thread is blocked!)
        if io_wait > 0:
            with io_pool.request() as io_req:
                yield io_req
                total_hold += io_wait
                yield env.timeout(io_wait)

        # CPU after I/O
        if cpu_post > 0:
            counters.busy_time += cpu_post
            total_hold += cpu_post
            yield env.timeout(cpu_post)

    counters.worker_occupied_time += total_hold


def _async_service(
        *,
        env: simpy.Environment,
        worker_pool: simpy.Resource,
        io_pool: simpy.Resource,
        counters: Memory,
        cpu_pre: float,
        cpu_post: float,
        io_wait: float,
):
    total_hold = 0.0

    # CPU before I/O
    if cpu_pre > 0:
        with worker_pool.request() as req1:
            yield req1
            counters.busy_time += cpu_pre
            total_hold += cpu_pre
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
            counters.busy_time += cpu_post
            total_hold += cpu_post
            yield env.timeout(cpu_post)

    counters.worker_occupied_time += total_hold


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
        io_times:  Callable[[], float],
        timeout_limit: float,
        rng: np.random.Generator,
        records: list[RequestRecord],
        counters: Memory,
        arrived_in_steady: Callable[[float], bool],
) -> Any:
    arrival_time = env.now

    def service() -> Any:
        total_cpu = cpu_times()
        split = rng.random()
        cpu_pre = total_cpu * split
        cpu_post = total_cpu * (1 - split)
        io_wait = io_times()

        try:
            yield from service_fn(
                env=env,
                worker_pool=worker_pool,
                io_pool=io_pool,
                cpu_pre=cpu_pre,
                cpu_post=cpu_post,
                io_wait=io_wait,
                counters=counters,
            )

            finish_time = env.now
            counters.completed += 1
            counters.in_system -= 1
            records.append(
                RequestRecord(
                    req_id=req_id,
                    arrival_time=arrival_time,
                    finish_time=finish_time,
                    latency_ms=finish_time - arrival_time,
                    arrived_in_steady=arrived_in_steady(arrival_time),
                )
            )
        except simpy.Interrupt:
            return

    svc_proc = env.process(service())
    if timeout_limit > 0:
        timeout_evt = env.timeout(timeout_limit)
        result = yield svc_proc | timeout_evt
        if timeout_evt in result:
            counters.timed_out += 1
            counters.in_system -= 1
            try:
                svc_proc.interrupt("timeout")
            except RuntimeError:
                pass
            return
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
        records: list[RequestRecord],
        service_fn: ServiceFn,
        counters: Memory,
        rng: np.random.Generator,
        cpu_times: Callable[[], float],
        io_times:  Callable[[], float],
        arrival_times:  Callable[[], float],
        warmup_ms: float,
        max_in_system: int,
        timeout_ms: float,
) -> Any:
    req_id = 0

    arrived_in_steady = lambda ms: warmup_ms <= ms
    while True:
        arrival = arrival_times()
        yield env.timeout(arrival)
        counters.arrivals += 1
        if counters.in_system >= max_in_system:
            counters.dropped += 1
            continue
        req_id += 1
        counters.in_system += 1
        env.process(
            _request_process(
                env=env,
                req_id=req_id,
                service_fn=service_fn,
                worker_pool=worker_pool,
                rng=rng,
                io_pool=io_pool,
                cpu_times=cpu_times,
                io_times=io_times,
                records=records,
                counters=counters,
                arrived_in_steady=arrived_in_steady,
                timeout_limit=timeout_ms,
            )
        )


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
) -> tuple[list[RequestRecord], Memory, int]:
    env = simpy.Environment()
    records: list[RequestRecord] = []
    counters = Memory()

    is_async = mode is ServerMode.async_mode
    num_threads = 1 if is_async else thread_count
    service_fn = _async_service if is_async else _sync_service
    worker_pool = simpy.Resource(env, capacity=num_threads)
    io_pool = simpy.Resource(env, capacity=io_limit)
    max_in_system = num_threads + queue_limit
    rng=np.random.default_rng(seed)


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
            records=records,
            counters=counters,
            max_in_system=max_in_system,
        )
    )
    env.run(until=sim_time_ms)
    return records, counters, num_threads
