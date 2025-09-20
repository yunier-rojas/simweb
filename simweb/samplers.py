import math

import numpy as np


def time_lognormal(*, rng: np.random.Generator, mean_ms: float, sigma: float = 1.0, **kwargs):
    # For LogNormal, arithmetic mean = exp(mu + sigma^2/2) => solve for mu
    mu = math.log(mean_ms) - 0.5 * (sigma ** 2)
    return lambda: float(rng.lognormal(mean=mu, sigma=sigma))


def time_exponential(*, rng: np.random.Generator, mean_ms: float, **kwargs):
    return lambda: float(rng.exponential(scale=mean_ms))


def arrival_poisson(*, rng: np.random.Generator, rate_rps: float, **kwargs):
    return lambda: float(rng.exponential(scale=1000.0 / rate_rps))


def arrival_bursty(
        *,
        rng: np.random.Generator,
        rate_rps: float,
        burst_factor: float = 5.0,
        burst_prob: float = 0.1,
        **kwargs
):
    def _sample():
        rate = rate_rps * (burst_factor if rng.random() < burst_prob else 1.0)
        return float(rng.exponential(scale=1000.0 / rate))

    return _sample
