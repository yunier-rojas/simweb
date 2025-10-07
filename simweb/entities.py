from enum import StrEnum


class ServerMode(StrEnum):
    sync_mode = "sync"
    async_mode = "async"


class RequestStatus(StrEnum):
    # A request is completed when it arrives after the warmup time, and it finished before the timeout
    completed = "completed"

    # A request is dropped when the worker has no more capacity to receive the request, after the warmup
    dropped = "dropped"

    # A request timeouts when it is not resolved before the timeout, also after the warm up
    timeout = "timeout"


class RecordField(StrEnum):
    # Core request-level fields
    REQ_ID = "req_id"
    ARRIVAL_TIME = "arrival_time"
    FINISH_TIME = "finish_time"
    LATENCY_MS = "latency_ms"
    STATUS = "status"

    # Experiment-level metadata fields
    THREAD_COUNT = "thread_count"
    MODE = "mode"
    REPLICATION = "replication"
    LABEL_IO = "label_io"
    LABEL_CPU = "label_cpu"
    LABEL_RATE = "label_rate"
    LABEL_IO_LIMIT = "label_io_limit"
    LABEL_QUEUE_LIMIT = "label_queue_limit"
    LABEL_TIMEOUT = "label_timeout"