#include <kore/kore.h>
#include <kore/http.h>

#include <errno.h>
#include <limits.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <getopt.h>

#define MODE_ASYNC "async"
#define MODE_SYNC "sync"

struct sim_config {
	long max_io_ms;
	long max_cpu_ms;
	double max_rt_factor;
	long max_total_ms;
	long max_inflight;
	long max_cpu_spin_ms;
	int json_pretty;
	char default_mode[6];
};

struct sim_state {
	struct http_request *req;
	char mode[6];
	long requested_io_ms;
	long requested_cpu_ms;
	double requested_rt_factor;
	long effective_io_ms;
	long effective_cpu_ms;
	long remaining_cpu_ms;
	uint64_t start_ns;
	uint64_t end_ns;
	int ok;
	char error_code[32];
	char error_message[160];
	struct kore_task task;
};

static struct sim_config sim_cfg = {
	.max_io_ms = 5000,
	.max_cpu_ms = 5000,
	.max_rt_factor = 20.0,
	.max_total_ms = -1,
	.max_inflight = 1000,
	.max_cpu_spin_ms = 5,
	.json_pretty = 0,
	.default_mode = MODE_ASYNC,
};

static atomic_long inflight_count = 0;

static void parse_args(int argc, char *argv[]);
static int parse_long(const char *value, long *out);
static int parse_double(const char *value, double *out);
static long clamp_long(long value, long min, long max);
static uint64_t now_ns(void);
static void busy_spin_ms(long cpu_ms);
static int parse_request(struct http_request *req, struct sim_state *state);
static void send_json_response(struct sim_state *state, int status);
static void finish_request(struct sim_state *state, int status);
static void inflight_decrement(void);

static void async_cpu_step(void *arg, u_int64_t now);
static void async_io_done(void *arg, u_int64_t now);
static void async_finalize(struct sim_state *state);

static void task_worker(struct kore_task *task);
static void task_done(struct kore_task *task);

int
kore_parent_configure(int argc, char *argv[])
{
	parse_args(argc, argv);
	return (KORE_RESULT_OK);
}

int
kore_worker_configure(int argc, char *argv[])
{
	parse_args(argc, argv);
	return (KORE_RESULT_OK);
}

int
sim_handler(struct http_request *req)
{
	struct sim_state *state;
	long inflight_after;

	inflight_after = atomic_fetch_add(&inflight_count, 1) + 1;
	if (sim_cfg.max_inflight > 0 && inflight_after > sim_cfg.max_inflight) {
		state = kore_calloc(1, sizeof(*state));
		state->req = req;
		state->start_ns = now_ns();
		state->ok = 0;
		kore_strlcpy(state->mode, sim_cfg.default_mode, sizeof(state->mode));
		snprintf(state->error_code, sizeof(state->error_code), "inflight_limit");
		snprintf(state->error_message, sizeof(state->error_message),
		    "inflight limit exceeded");
		finish_request(state, 429);
		return (KORE_RESULT_OK);
	}

	state = kore_calloc(1, sizeof(*state));
	state->req = req;
	state->start_ns = now_ns();
	state->ok = 0;

	if (!parse_request(req, state)) {
		finish_request(state, 400);
		return (KORE_RESULT_OK);
	}

	if (strcmp(state->mode, MODE_SYNC) == 0) {
		kore_task_create(&state->task, task_worker);
		state->task.arg = state;
		kore_task_bind_request(&state->task, req);
		kore_task_bind_callback(&state->task, task_done);
		kore_task_run(&state->task);
		return (KORE_RESULT_OK);
	}

	state->remaining_cpu_ms = state->effective_cpu_ms;
	kore_timer_add(async_cpu_step, 0, state, 0);
	return (KORE_RESULT_OK);
}

static void
parse_args(int argc, char *argv[])
{
	int opt;
	int opt_index = 0;
	static struct option opts[] = {
		{"max-io-ms", required_argument, NULL, 'i'},
		{"max-cpu-ms", required_argument, NULL, 'c'},
		{"max-rt-factor", required_argument, NULL, 'r'},
		{"max-total-ms", required_argument, NULL, 't'},
		{"max-inflight", required_argument, NULL, 'n'},
		{"max-cpu-spin-ms", required_argument, NULL, 's'},
		{"default-mode", required_argument, NULL, 'm'},
		{"json-pretty", required_argument, NULL, 'j'},
		{NULL, 0, NULL, 0}
	};

	optind = 1;
	while ((opt = getopt_long(argc, argv, "i:c:r:t:n:s:m:j:", opts, &opt_index)) != -1) {
		switch (opt) {
		case 'i':
			parse_long(optarg, &sim_cfg.max_io_ms);
			break;
		case 'c':
			parse_long(optarg, &sim_cfg.max_cpu_ms);
			break;
		case 'r':
			parse_double(optarg, &sim_cfg.max_rt_factor);
			break;
		case 't':
			parse_long(optarg, &sim_cfg.max_total_ms);
			break;
		case 'n':
			parse_long(optarg, &sim_cfg.max_inflight);
			break;
		case 's':
			parse_long(optarg, &sim_cfg.max_cpu_spin_ms);
			break;
		case 'm':
			if (strcmp(optarg, MODE_SYNC) == 0 || strcmp(optarg, MODE_ASYNC) == 0) {
				kore_strlcpy(sim_cfg.default_mode, optarg, sizeof(sim_cfg.default_mode));
			}
			break;
		case 'j':
			sim_cfg.json_pretty = atoi(optarg) ? 1 : 0;
			break;
		default:
			break;
		}
	}
}

static int
parse_long(const char *value, long *out)
{
	char *end = NULL;
	long parsed;

	errno = 0;
	parsed = strtol(value, &end, 10);
	if (errno != 0 || end == value || *end != '\0') {
		return (KORE_RESULT_ERROR);
	}
	*out = parsed;
	return (KORE_RESULT_OK);
}

static int
parse_double(const char *value, double *out)
{
	char *end = NULL;
	double parsed;

	errno = 0;
	parsed = strtod(value, &end);
	if (errno != 0 || end == value || *end != '\0') {
		return (KORE_RESULT_ERROR);
	}
	*out = parsed;
	return (KORE_RESULT_OK);
}

static long
clamp_long(long value, long min, long max)
{
	if (value < min) {
		return min;
	}
	if (value > max) {
		return max;
	}
	return value;
}

static uint64_t
now_ns(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ((uint64_t)ts.tv_sec * 1000000000ull) + (uint64_t)ts.tv_nsec;
}

static void
busy_spin_ms(long cpu_ms)
{
	uint64_t start = now_ns();
	uint64_t target = start + ((uint64_t)cpu_ms * 1000000ull);
	volatile uint64_t sink = 0;

	while (now_ns() < target) {
		sink += 3;
		sink ^= sink << 1;
	}

	(void)sink;
}

static int
parse_request(struct http_request *req, struct sim_state *state)
{
	char *value = NULL;
	long io_ms = 0;
	long cpu_ms = 0;
	double rt_factor = 1.0;
	long effective_io;
	long effective_cpu;
	double scaled;

	kore_strlcpy(state->mode, sim_cfg.default_mode, sizeof(state->mode));

	if (http_argument_get_string(req, "mode", &value)) {
		if (strcmp(value, MODE_SYNC) == 0 || strcmp(value, MODE_ASYNC) == 0) {
			kore_strlcpy(state->mode, value, sizeof(state->mode));
		} else {
			snprintf(state->error_code, sizeof(state->error_code), "invalid_mode");
			snprintf(state->error_message, sizeof(state->error_message), "mode must be sync or async");
			return 0;
		}
	} else {
		kore_strlcpy(state->mode, sim_cfg.default_mode, sizeof(state->mode));
	}

	if (http_argument_get_string(req, "io_ms", &value)) {
		if (parse_long(value, &io_ms) != KORE_RESULT_OK || io_ms < 0) {
			snprintf(state->error_code, sizeof(state->error_code), "invalid_io_ms");
			snprintf(state->error_message, sizeof(state->error_message), "io_ms must be a non-negative integer");
			return 0;
		}
	} else {
		snprintf(state->error_code, sizeof(state->error_code), "missing_io_ms");
		snprintf(state->error_message, sizeof(state->error_message), "io_ms is required");
		return 0;
	}

	if (http_argument_get_string(req, "cpu_ms", &value)) {
		if (parse_long(value, &cpu_ms) != KORE_RESULT_OK || cpu_ms < 0) {
			snprintf(state->error_code, sizeof(state->error_code), "invalid_cpu_ms");
			snprintf(state->error_message, sizeof(state->error_message), "cpu_ms must be a non-negative integer");
			return 0;
		}
	} else {
		snprintf(state->error_code, sizeof(state->error_code), "missing_cpu_ms");
		snprintf(state->error_message, sizeof(state->error_message), "cpu_ms is required");
		return 0;
	}

	if (http_argument_get_string(req, "rt_factor", &value)) {
		if (parse_double(value, &rt_factor) != KORE_RESULT_OK || rt_factor < 0.0) {
			snprintf(state->error_code, sizeof(state->error_code), "invalid_rt_factor");
			snprintf(state->error_message, sizeof(state->error_message), "rt_factor must be a non-negative float");
			return 0;
		}
	} else {
		snprintf(state->error_code, sizeof(state->error_code), "missing_rt_factor");
		snprintf(state->error_message, sizeof(state->error_message), "rt_factor is required");
		return 0;
	}

	if (rt_factor > sim_cfg.max_rt_factor) {
		snprintf(state->error_code, sizeof(state->error_code), "rt_factor_too_large");
		snprintf(state->error_message, sizeof(state->error_message), "rt_factor exceeds max_rt_factor");
		return 0;
	}

	effective_io = clamp_long(io_ms, 0, sim_cfg.max_io_ms);

	scaled = (double)cpu_ms * rt_factor;
	effective_cpu = (long)scaled;
	effective_cpu = clamp_long(effective_cpu, 0, sim_cfg.max_cpu_ms);

	if (sim_cfg.max_total_ms > 0 && (effective_io + effective_cpu) > sim_cfg.max_total_ms) {
		snprintf(state->error_code, sizeof(state->error_code), "total_ms_exceeded");
		snprintf(state->error_message, sizeof(state->error_message), "effective total exceeds max_total_ms");
		return 0;
	}

	state->requested_io_ms = io_ms;
	state->requested_cpu_ms = cpu_ms;
	state->requested_rt_factor = rt_factor;
	state->effective_io_ms = effective_io;
	state->effective_cpu_ms = effective_cpu;
	return 1;
}

static void
send_json_response(struct sim_state *state, int status)
{
	char payload[1024];
	const char *pretty = sim_cfg.json_pretty ? "\n" : "";
	const char *indent = sim_cfg.json_pretty ? "  " : "";
	const char *indent2 = sim_cfg.json_pretty ? "    " : "";
	uint64_t elapsed_ns;
	double elapsed_ms;

	state->end_ns = now_ns();
	elapsed_ns = state->end_ns - state->start_ns;
	elapsed_ms = (double)elapsed_ns / 1000000.0;

	snprintf(payload, sizeof(payload),
		"{%s"
		"%s\"ok\": %s,%s"
		"%s\"mode\": \"%s\",%s"
		"%s\"requested\": {%s\"io_ms\": %ld,%s\"cpu_ms\": %ld,%s\"rt_factor\": %.3f%s},%s"
		"%s\"effective\": {%s\"io_ms\": %ld,%s\"cpu_ms\": %ld%s},%s"
		"%s\"server\": {%s\"inflight\": %ld,%s\"max_inflight\": %ld%s},%s"
		"%s\"timing\": {%s\"start_monotonic_ns\": %llu,%s\"end_monotonic_ns\": %llu,%s\"elapsed_ms\": %.3f%s},%s"
		"%s\"error\": {%s\"code\": \"%s\",%s\"message\": \"%s\"%s}%s"
		"%s}%s",
		pretty,
		indent, state->ok ? "true" : "false", pretty,
		indent, state->mode, pretty,
		indent, indent2, state->requested_io_ms, pretty,
		indent2, state->requested_cpu_ms, pretty,
		indent2, state->requested_rt_factor, indent, pretty,
		indent, indent2, state->effective_io_ms, pretty,
		indent2, state->effective_cpu_ms, indent, pretty,
		indent, indent2, atomic_load(&inflight_count), pretty,
		indent2, sim_cfg.max_inflight, indent, pretty,
		indent, indent2, (unsigned long long)state->start_ns, pretty,
		indent2, (unsigned long long)state->end_ns, pretty,
		indent2, elapsed_ms, indent, pretty,
		indent, indent2, state->error_code, pretty,
		indent2, state->error_message, indent, pretty,
		indent, pretty
	);

	http_response_header(state->req, "content-type", "application/json");
	http_response_header(state->req, "X-Sim-Mode", state->mode);
	{
		char elapsed_buf[64];
		snprintf(elapsed_buf, sizeof(elapsed_buf), "%.3f", elapsed_ms);
		http_response_header(state->req, "X-Sim-Elapsed-Ms", elapsed_buf);
	}
	if (status == 0) {
		status = 200;
	}
	http_response(state->req, status, payload, strlen(payload));
}

static void
finish_request(struct sim_state *state, int status)
{
	send_json_response(state, status);
	inflight_decrement();
	kore_free(state);
}

static void
inflight_decrement(void)
{
	atomic_fetch_sub(&inflight_count, 1);
}

static void
async_cpu_step(void *arg, u_int64_t now)
{
	struct sim_state *state = arg;
	long slice_ms = 2;
	long work_ms;

	(void)now;
	if (sim_cfg.max_cpu_spin_ms > 0 && sim_cfg.max_cpu_spin_ms < slice_ms) {
		slice_ms = sim_cfg.max_cpu_spin_ms;
	}

	if (state->remaining_cpu_ms <= 0) {
		if (state->effective_io_ms > 0) {
			kore_timer_add(async_io_done, state->effective_io_ms, state, 0);
			return;
		}
		async_finalize(state);
		return;
	}

	work_ms = state->remaining_cpu_ms < slice_ms ? state->remaining_cpu_ms : slice_ms;
	busy_spin_ms(work_ms);
	state->remaining_cpu_ms -= work_ms;
	kore_timer_add(async_cpu_step, 0, state, 0);
}

static void
async_io_done(void *arg, u_int64_t now)
{
	struct sim_state *state = arg;
	(void)now;
	async_finalize(state);
}

static void
async_finalize(struct sim_state *state)
{
	state->ok = 1;
	state->error_code[0] = '\0';
	state->error_message[0] = '\0';
	finish_request(state, 200);
}

static void
task_worker(struct kore_task *task)
{
	struct sim_state *state = task->arg;
	struct timespec ts;

	if (state->effective_cpu_ms > 0) {
		busy_spin_ms(state->effective_cpu_ms);
	}

	if (state->effective_io_ms > 0) {
		ts.tv_sec = state->effective_io_ms / 1000;
		ts.tv_nsec = (state->effective_io_ms % 1000) * 1000000L;
		nanosleep(&ts, NULL);
	}
}

static void
task_done(struct kore_task *task)
{
	struct sim_state *state = task->arg;

	kore_task_destroy(&state->task);
	state->ok = 1;
	state->error_code[0] = '\0';
	state->error_message[0] = '\0';
	finish_request(state, 200);
}
