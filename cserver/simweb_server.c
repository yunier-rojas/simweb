#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <pthread.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define STATUS_COMPLETED 0
#define STATUS_TIMEOUT 1
#define STATUS_DROPPED 2

#define DEFAULT_PORT 8080
#define DEFAULT_CPU_PRE_MS 2
#define DEFAULT_CPU_POST_MS 2
#define DEFAULT_IO_WAIT_MS 10
#define DEFAULT_THREAD_COUNT 4
#define DEFAULT_QUEUE_LIMIT 64
#define DEFAULT_TIMEOUT_MS 0

#define MAX_EVENTS 64
#define MAX_FDS 65536

static volatile sig_atomic_t g_running = 1;

typedef struct {
    int port;
    bool async_mode;
    long cpu_pre_ms;
    long cpu_post_ms;
    long io_wait_ms;
    int thread_count;
    int queue_limit;
    long timeout_ms;
} Config;

typedef struct {
    int fd;
    long arrival_ms;
    long deadline_ms;
} SyncRequest;

typedef struct {
    SyncRequest *items;
    int capacity;
    int size;
    int head;
    int tail;
    pthread_mutex_t mutex;
    pthread_cond_t cond;
} RequestQueue;

typedef enum {
    STAGE_CPU_PRE,
    STAGE_IO_WAIT,
    STAGE_CPU_POST,
    STAGE_DONE
} ConnStage;

typedef struct {
    int fd;
    bool active;
    long arrival_ms;
    long deadline_ms;
    ConnStage stage;
    long io_ready_ms;
} ConnState;

static void handle_signal(int sig) {
    (void)sig;
    g_running = 0;
}

static long now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long)(ts.tv_sec * 1000L + ts.tv_nsec / 1000000L);
}

static void log_request(long arrival_ms, long finish_ms, int status) {
    long latency = finish_ms - arrival_ms;
    if (latency < 0) {
        latency = 0;
    }
    printf("%ld,%ld,%ld,%d\n", arrival_ms, finish_ms, latency, status);
    fflush(stdout);
}

static long env_long(const char *key, long fallback) {
    const char *value = getenv(key);
    if (!value || *value == '\0') {
        return fallback;
    }
    return strtol(value, NULL, 10);
}

static int env_int(const char *key, int fallback) {
    const char *value = getenv(key);
    if (!value || *value == '\0') {
        return fallback;
    }
    return (int)strtol(value, NULL, 10);
}

static void busy_wait_ms(long duration_ms, long deadline_ms, bool *timed_out) {
    long start = now_ms();
    long end = start + duration_ms;
    while (now_ms() < end) {
        if (deadline_ms > 0 && now_ms() >= deadline_ms) {
            *timed_out = true;
            return;
        }
    }
}

static void sleep_blocking_ms(long duration_ms, long deadline_ms, bool *timed_out) {
    long start = now_ms();
    long end = start + duration_ms;
    while (now_ms() < end) {
        if (deadline_ms > 0 && now_ms() >= deadline_ms) {
            *timed_out = true;
            return;
        }
        struct timespec ts;
        ts.tv_sec = 0;
        ts.tv_nsec = 1000000L;
        nanosleep(&ts, NULL);
    }
}

static void queue_init(RequestQueue *queue, int capacity) {
    queue->items = calloc((size_t)capacity, sizeof(SyncRequest));
    queue->capacity = capacity;
    queue->size = 0;
    queue->head = 0;
    queue->tail = 0;
    pthread_mutex_init(&queue->mutex, NULL);
    pthread_cond_init(&queue->cond, NULL);
}

static void queue_destroy(RequestQueue *queue) {
    free(queue->items);
    pthread_mutex_destroy(&queue->mutex);
    pthread_cond_destroy(&queue->cond);
}

static bool queue_push(RequestQueue *queue, SyncRequest req) {
    if (queue->size >= queue->capacity) {
        return false;
    }
    queue->items[queue->tail] = req;
    queue->tail = (queue->tail + 1) % queue->capacity;
    queue->size++;
    pthread_cond_signal(&queue->cond);
    return true;
}

static bool queue_pop(RequestQueue *queue, SyncRequest *req) {
    while (queue->size == 0 && g_running) {
        pthread_cond_wait(&queue->cond, &queue->mutex);
    }
    if (queue->size == 0) {
        return false;
    }
    *req = queue->items[queue->head];
    queue->head = (queue->head + 1) % queue->capacity;
    queue->size--;
    return true;
}

static int set_nonblocking(int fd) {
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags == -1) {
        return -1;
    }
    return fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

static int create_listen_socket(int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        perror("socket");
        return -1;
    }
    int opt = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons((uint16_t)port);

    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(fd);
        return -1;
    }
    if (listen(fd, 1024) < 0) {
        perror("listen");
        close(fd);
        return -1;
    }
    return fd;
}

static void send_response(int fd) {
    const char *response =
        "HTTP/1.1 200 OK\r\n"
        "Content-Length: 2\r\n"
        "Connection: close\r\n"
        "\r\n"
        "OK";
    send(fd, response, strlen(response), 0);
}

static void process_sync_request(const Config *config, SyncRequest req) {
    bool timed_out = false;
    long finish_ms;

    busy_wait_ms(config->cpu_pre_ms, req.deadline_ms, &timed_out);
    if (!timed_out) {
        sleep_blocking_ms(config->io_wait_ms, req.deadline_ms, &timed_out);
    }
    if (!timed_out) {
        busy_wait_ms(config->cpu_post_ms, req.deadline_ms, &timed_out);
    }

    finish_ms = now_ms();
    if (timed_out) {
        if (req.deadline_ms > 0 && finish_ms < req.deadline_ms) {
            finish_ms = req.deadline_ms;
        }
        log_request(req.arrival_ms, finish_ms, STATUS_TIMEOUT);
        close(req.fd);
        return;
    }

    send_response(req.fd);
    close(req.fd);
    log_request(req.arrival_ms, finish_ms, STATUS_COMPLETED);
}

typedef struct {
    const Config *config;
    RequestQueue *queue;
    pthread_mutex_t *count_mutex;
    int *in_system;
} WorkerArgs;

static void *worker_thread(void *arg) {
    WorkerArgs *args = (WorkerArgs *)arg;
    while (g_running) {
        SyncRequest req;
        pthread_mutex_lock(&args->queue->mutex);
        bool ok = queue_pop(args->queue, &req);
        pthread_mutex_unlock(&args->queue->mutex);
        if (!ok) {
            continue;
        }
        process_sync_request(args->config, req);
        pthread_mutex_lock(args->count_mutex);
        (*args->in_system)--;
        pthread_mutex_unlock(args->count_mutex);
    }
    return NULL;
}

static void run_sync_server(const Config *config) {
    int listen_fd = create_listen_socket(config->port);
    if (listen_fd < 0) {
        return;
    }
    RequestQueue queue;
    queue_init(&queue, config->queue_limit > 0 ? config->queue_limit : 1);

    pthread_t *threads = calloc((size_t)config->thread_count, sizeof(pthread_t));
    pthread_mutex_t count_mutex = PTHREAD_MUTEX_INITIALIZER;
    int in_system = 0;

    WorkerArgs args = {
        .config = config,
        .queue = &queue,
        .count_mutex = &count_mutex,
        .in_system = &in_system,
    };

    for (int i = 0; i < config->thread_count; i++) {
        pthread_create(&threads[i], NULL, worker_thread, &args);
    }

    while (g_running) {
        struct sockaddr_in client_addr;
        socklen_t client_len = sizeof(client_addr);
        int client_fd = accept(listen_fd, (struct sockaddr *)&client_addr, &client_len);
        if (client_fd < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("accept");
            break;
        }

        long arrival = now_ms();
        long deadline = config->timeout_ms > 0 ? arrival + config->timeout_ms : 0;
        int max_in_system = config->thread_count + config->queue_limit;

        pthread_mutex_lock(&count_mutex);
        if (in_system >= max_in_system) {
            pthread_mutex_unlock(&count_mutex);
            log_request(arrival, arrival, STATUS_DROPPED);
            close(client_fd);
            continue;
        }
        in_system++;
        pthread_mutex_unlock(&count_mutex);

        SyncRequest req = {
            .fd = client_fd,
            .arrival_ms = arrival,
            .deadline_ms = deadline,
        };

        pthread_mutex_lock(&queue.mutex);
        if (!queue_push(&queue, req)) {
            pthread_mutex_unlock(&queue.mutex);
            log_request(arrival, arrival, STATUS_DROPPED);
            close(client_fd);
            pthread_mutex_lock(&count_mutex);
            in_system--;
            pthread_mutex_unlock(&count_mutex);
            continue;
        }
        pthread_mutex_unlock(&queue.mutex);
    }

    g_running = 0;
    pthread_cond_broadcast(&queue.cond);

    for (int i = 0; i < config->thread_count; i++) {
        pthread_join(threads[i], NULL);
    }

    free(threads);
    queue_destroy(&queue);
    close(listen_fd);
}

static void run_async_server(const Config *config) {
    int listen_fd = create_listen_socket(config->port);
    if (listen_fd < 0) {
        return;
    }
    if (set_nonblocking(listen_fd) < 0) {
        perror("set_nonblocking");
        close(listen_fd);
        return;
    }

    int epoll_fd = epoll_create1(0);
    if (epoll_fd < 0) {
        perror("epoll_create1");
        close(listen_fd);
        return;
    }

    struct epoll_event ev;
    ev.events = EPOLLIN;
    ev.data.fd = listen_fd;
    if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, listen_fd, &ev) < 0) {
        perror("epoll_ctl");
        close(epoll_fd);
        close(listen_fd);
        return;
    }

    ConnState *states = calloc(MAX_FDS, sizeof(ConnState));
    int *active_fds = calloc(MAX_FDS, sizeof(int));
    int active_count = 0;

    struct epoll_event events[MAX_EVENTS];

    while (g_running) {
        long now = now_ms();
        long next_wakeup = -1;
        for (int i = 0; i < active_count; i++) {
            ConnState *state = &states[active_fds[i]];
            if (!state->active) {
                continue;
            }
            if (state->deadline_ms > 0) {
                if (next_wakeup == -1 || state->deadline_ms < next_wakeup) {
                    next_wakeup = state->deadline_ms;
                }
            }
            if (state->stage == STAGE_IO_WAIT) {
                if (next_wakeup == -1 || state->io_ready_ms < next_wakeup) {
                    next_wakeup = state->io_ready_ms;
                }
            }
        }
        int timeout_ms = -1;
        if (next_wakeup != -1) {
            long diff = next_wakeup - now;
            timeout_ms = diff > 0 ? (int)diff : 0;
        }

        int n = epoll_wait(epoll_fd, events, MAX_EVENTS, timeout_ms);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("epoll_wait");
            break;
        }

        for (int i = 0; i < n; i++) {
            if (events[i].data.fd == listen_fd) {
                while (true) {
                    struct sockaddr_in client_addr;
                    socklen_t client_len = sizeof(client_addr);
                    int client_fd = accept(listen_fd, (struct sockaddr *)&client_addr, &client_len);
                    if (client_fd < 0) {
                        if (errno == EAGAIN || errno == EWOULDBLOCK) {
                            break;
                        }
                        perror("accept");
                        break;
                    }
                    if (client_fd >= MAX_FDS) {
                        close(client_fd);
                        continue;
                    }
                    long arrival = now_ms();
                    long deadline = config->timeout_ms > 0 ? arrival + config->timeout_ms : 0;
                    int max_in_system = 1 + config->queue_limit;

                    if (active_count >= max_in_system) {
                        log_request(arrival, arrival, STATUS_DROPPED);
                        close(client_fd);
                        continue;
                    }

                    states[client_fd].fd = client_fd;
                    states[client_fd].active = true;
                    states[client_fd].arrival_ms = arrival;
                    states[client_fd].deadline_ms = deadline;
                    states[client_fd].stage = STAGE_CPU_PRE;
                    states[client_fd].io_ready_ms = 0;
                    active_fds[active_count++] = client_fd;
                }
            }
        }

        now = now_ms();
        for (int i = 0; i < active_count; ) {
            int fd = active_fds[i];
            ConnState *state = &states[fd];
            if (!state->active) {
                i++;
                continue;
            }
            if (state->deadline_ms > 0 && now >= state->deadline_ms) {
                log_request(state->arrival_ms, state->deadline_ms, STATUS_TIMEOUT);
                close(state->fd);
                state->active = false;
                active_fds[i] = active_fds[active_count - 1];
                active_count--;
                continue;
            }

            if (state->stage == STAGE_CPU_PRE) {
                bool timed_out = false;
                busy_wait_ms(config->cpu_pre_ms, state->deadline_ms, &timed_out);
                if (timed_out) {
                    log_request(state->arrival_ms, state->deadline_ms, STATUS_TIMEOUT);
                    close(state->fd);
                    state->active = false;
                    active_fds[i] = active_fds[active_count - 1];
                    active_count--;
                    continue;
                }
                if (config->io_wait_ms > 0) {
                    state->stage = STAGE_IO_WAIT;
                    state->io_ready_ms = now_ms() + config->io_wait_ms;
                } else {
                    state->stage = STAGE_CPU_POST;
                }
            }

            if (state->stage == STAGE_IO_WAIT) {
                if (now_ms() >= state->io_ready_ms) {
                    state->stage = STAGE_CPU_POST;
                } else {
                    i++;
                    continue;
                }
            }

            if (state->stage == STAGE_CPU_POST) {
                bool timed_out = false;
                busy_wait_ms(config->cpu_post_ms, state->deadline_ms, &timed_out);
                if (timed_out) {
                    log_request(state->arrival_ms, state->deadline_ms, STATUS_TIMEOUT);
                    close(state->fd);
                    state->active = false;
                    active_fds[i] = active_fds[active_count - 1];
                    active_count--;
                    continue;
                }
                send_response(state->fd);
                close(state->fd);
                log_request(state->arrival_ms, now_ms(), STATUS_COMPLETED);
                state->active = false;
                active_fds[i] = active_fds[active_count - 1];
                active_count--;
                continue;
            }

            i++;
        }
    }

    free(active_fds);
    free(states);
    close(epoll_fd);
    close(listen_fd);
}

static void usage(const char *prog) {
    fprintf(stderr,
            "Usage: %s [--mode sync|async] [--port N] [--cpu-pre-ms N] [--cpu-post-ms N]\n"
            "           [--io-wait-ms N] [--thread-count N] [--queue-limit N] [--timeout-ms N]\n",
            prog);
}

static Config parse_args(int argc, char **argv) {
    Config config = {
        .port = env_int("SIMWEB_PORT", DEFAULT_PORT),
        .async_mode = false,
        .cpu_pre_ms = env_long("SIMWEB_CPU_PRE_MS", DEFAULT_CPU_PRE_MS),
        .cpu_post_ms = env_long("SIMWEB_CPU_POST_MS", DEFAULT_CPU_POST_MS),
        .io_wait_ms = env_long("SIMWEB_IO_WAIT_MS", DEFAULT_IO_WAIT_MS),
        .thread_count = env_int("SIMWEB_THREAD_COUNT", DEFAULT_THREAD_COUNT),
        .queue_limit = env_int("SIMWEB_QUEUE_LIMIT", DEFAULT_QUEUE_LIMIT),
        .timeout_ms = env_long("SIMWEB_TIMEOUT_MS", DEFAULT_TIMEOUT_MS),
    };

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--mode") == 0 && i + 1 < argc) {
            const char *mode = argv[++i];
            if (strcmp(mode, "async") == 0) {
                config.async_mode = true;
            } else if (strcmp(mode, "sync") == 0) {
                config.async_mode = false;
            } else {
                usage(argv[0]);
                exit(1);
            }
        } else if (strcmp(argv[i], "--port") == 0 && i + 1 < argc) {
            config.port = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--cpu-pre-ms") == 0 && i + 1 < argc) {
            config.cpu_pre_ms = strtol(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--cpu-post-ms") == 0 && i + 1 < argc) {
            config.cpu_post_ms = strtol(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--io-wait-ms") == 0 && i + 1 < argc) {
            config.io_wait_ms = strtol(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--thread-count") == 0 && i + 1 < argc) {
            config.thread_count = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--queue-limit") == 0 && i + 1 < argc) {
            config.queue_limit = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--timeout-ms") == 0 && i + 1 < argc) {
            config.timeout_ms = strtol(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            usage(argv[0]);
            exit(0);
        } else {
            usage(argv[0]);
            exit(1);
        }
    }

    if (config.thread_count < 1) {
        config.thread_count = 1;
    }
    if (config.queue_limit < 0) {
        config.queue_limit = 0;
    }
    return config;
}

int main(int argc, char **argv) {
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);

    Config config = parse_args(argc, argv);
    fprintf(stderr,
            "Starting %s server on port %d (cpu_pre=%ldms cpu_post=%ldms io_wait=%ldms threads=%d queue=%d timeout=%ldms)\n",
            config.async_mode ? "async" : "sync",
            config.port,
            config.cpu_pre_ms,
            config.cpu_post_ms,
            config.io_wait_ms,
            config.thread_count,
            config.queue_limit,
            config.timeout_ms);

    if (config.async_mode) {
        if (config.thread_count != 1) {
            fprintf(stderr, "Async mode uses a single event loop thread; ignoring thread_count=%d\n", config.thread_count);
        }
        run_async_server(&config);
    } else {
        run_sync_server(&config);
    }

    fprintf(stderr, "Server stopped.\n");
    return 0;
}
