from dataclasses import dataclass, field
from enum import Enum

import numpy


class ServerMode(str, Enum):
    sync_mode = 'sync_mode'
    async_mode = 'async_mode'


@dataclass(frozen=True)
class RequestRecord:
    req_id: int
    arrival_time: float
    finish_time: float
    latency_ms: float
    arrived_in_steady: bool


@dataclass
class Memory:
    arrivals: int = field(default=0)
    completed: int = field(default=0)
    dropped: int = field(default=0)
    timed_out: int = field(default=0)
    in_system: int = field(default=0)
    busy_time: int = field(default=0)
    worker_occupied_time: float = field(default=0)


@dataclass(frozen=True)
class Metrics:
    total_arrivals: int
    total_completed: int
    total_dropped: int
    total_timed_out: int
    success_rate: float
    latency_ms: numpy.ndarray
    throughput_rps: float
    saturation: float

