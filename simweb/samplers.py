import math
import numpy as np


def time_lognormal(*, rng: np.random.Generator, mean_ms: float, sigma: float = 1.0, **kwargs):
    """Return a sampler for lognormal service times (in ms)."""
    mu = math.log(mean_ms) - 0.5 * (sigma**2)
    return lambda: float(rng.lognormal(mean=mu, sigma=sigma))


def time_exponential(*, rng: np.random.Generator, mean_ms: float, **kwargs):
    """Return a sampler for exponential service times (in ms)."""
    return lambda: float(rng.exponential(scale=mean_ms))


def arrival_poisson(*, rng: np.random.Generator, rate_rps: float, **kwargs):
    """Return exponential inter-arrival times (in ms) for a given request rate (rps)."""
    rate_per_ms = rate_rps / 1000.0  # convert requests per second → requests per ms
    return lambda: float(rng.exponential(scale=1.0 / rate_per_ms))


def arrival_bursty(
        *,
        rng: np.random.Generator,
        rate_rps: float,
        burst_factor: float = 5.0,
        burst_prob: float = 0.1,
        **kwargs
):
    """Return a bursty arrival sampler (in ms)."""
    def _sample():
        rate_per_ms = rate_rps / 1000.0
        if rng.random() < burst_prob:
            rate_per_ms *= burst_factor
        return float(rng.exponential(scale=1.0 / rate_per_ms))

    return _sample
