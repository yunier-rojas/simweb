import time

from simweb import simulate_server
from simweb.entities import ServerMode

start = time.time()
_ = simulate_server(
    mode=ServerMode.sync_mode,
    thread_count=1,
    cpu_mean_ms=100.0,
    io_mean_ms=100.0,
    rate_rps=100.0,
    io_limit=100,
    queue_limit=100,
    timeout_ms=100.0,
    sim_time_ms=100_000.0,
    warmup_ms=0.0,
    seed=42,
)
elapsed = (time.time() - start) * 1000  # convert to ms
print(f"Sample run took {elapsed:.2f} ms")
