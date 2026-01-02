import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';
import { randomSeed } from 'k6';

const serverElapsed = new Trend('server_elapsed_ms', true);

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8888';
const PATH = __ENV.PATH || '/sim';
const RPS = parseInt(__ENV.RPS || '50', 10);
const DURATION = __ENV.DURATION || '30s';
const PRE_VUS = parseInt(__ENV.PRE_VUS || '50', 10);
const MAX_VUS = parseInt(__ENV.MAX_VUS || '200', 10);
const TIMEOUT = __ENV.TIMEOUT || '2s';
const MODE = __ENV.MODE || 'async';
const MIX_ASYNC = parseInt(__ENV.MIX_ASYNC || '50', 10);
const EXECUTOR = __ENV.EXECUTOR || 'constant';
const OUT_JSON = __ENV.OUT_JSON || '';
const SEED = parseInt(__ENV.SEED || '12345', 10);

const IO_MS = __ENV.IO_MS || '50';
const CPU_MS = __ENV.CPU_MS || '10';
const RT_FACTOR = __ENV.RT_FACTOR || '1.0';

function parseDistribution(raw, name) {
  if (!raw || raw.length === 0) {
    throw new Error(`${name} is required`);
  }
  if (raw.startsWith('uniform:')) {
    const parts = raw.replace('uniform:', '').split(':');
    if (parts.length !== 2) {
      throw new Error(`${name} uniform format must be uniform:min:max`);
    }
    const min = parseFloat(parts[0]);
    const max = parseFloat(parts[1]);
    if (!Number.isFinite(min) || !Number.isFinite(max) || min > max) {
      throw new Error(`${name} uniform bounds are invalid`);
    }
    return () => min + Math.random() * (max - min);
  }
  if (raw.startsWith('list:')) {
    const values = raw.replace('list:', '').split(',').map((v) => parseFloat(v));
    if (!values.length || values.some((v) => !Number.isFinite(v))) {
      throw new Error(`${name} list values are invalid`);
    }
    return () => values[Math.floor(Math.random() * values.length)];
  }
  if (raw.startsWith('wlist:')) {
    const items = raw.replace('wlist:', '').split(',');
    const values = [];
    const weights = [];
    let total = 0;
    for (const item of items) {
      const [valueStr, weightStr] = item.split(':');
      const value = parseFloat(valueStr);
      const weight = parseFloat(weightStr);
      if (!Number.isFinite(value) || !Number.isFinite(weight) || weight <= 0) {
        throw new Error(`${name} weighted list values are invalid`);
      }
      values.push(value);
      weights.push(weight);
      total += weight;
    }
    return () => {
      const r = Math.random() * total;
      let acc = 0;
      for (let i = 0; i < values.length; i += 1) {
        acc += weights[i];
        if (r <= acc) {
          return values[i];
        }
      }
      return values[values.length - 1];
    };
  }
  const fixed = parseFloat(raw);
  if (!Number.isFinite(fixed)) {
    throw new Error(`${name} fixed value is invalid`);
  }
  return () => fixed;
}

const ioSampler = parseDistribution(IO_MS, 'IO_MS');
const cpuSampler = parseDistribution(CPU_MS, 'CPU_MS');
const rtSampler = parseDistribution(RT_FACTOR, 'RT_FACTOR');

if (!['async', 'sync', 'mix'].includes(MODE)) {
  throw new Error('MODE must be async, sync, or mix');
}
if (MODE === 'mix' && (MIX_ASYNC < 0 || MIX_ASYNC > 100)) {
  throw new Error('MIX_ASYNC must be between 0 and 100');
}

randomSeed(SEED);

export const options = {
  scenarios: {
    sim: EXECUTOR === 'ramping'
      ? {
          executor: 'ramping-arrival-rate',
          timeUnit: '1s',
          preAllocatedVUs: PRE_VUS,
          maxVUs: MAX_VUS,
          stages: JSON.parse(__ENV.RAMPING_STAGES || '[{"target":50,"duration":"30s"}]'),
        }
      : {
          executor: 'constant-arrival-rate',
          rate: RPS,
          timeUnit: '1s',
          duration: DURATION,
          preAllocatedVUs: PRE_VUS,
          maxVUs: MAX_VUS,
        },
  },
};

export default function () {
  const mode = MODE === 'mix'
    ? (Math.random() * 100 < MIX_ASYNC ? 'async' : 'sync')
    : MODE;
  const ioMs = ioSampler();
  const cpuMs = cpuSampler();
  const rtFactor = rtSampler();

  const url = `${BASE_URL}${PATH}?mode=${mode}&io_ms=${ioMs.toFixed(0)}&cpu_ms=${cpuMs.toFixed(0)}&rt_factor=${rtFactor.toFixed(3)}`;
  const res = http.get(url, {
    timeout: TIMEOUT,
    tags: { mode },
  });

  const ok = check(res, {
    'status is 200': (r) => r.status === 200,
  });

  if (ok) {
    let elapsed = null;
    if (res.headers['X-Sim-Elapsed-Ms']) {
      elapsed = parseFloat(res.headers['X-Sim-Elapsed-Ms']);
    } else {
      try {
        const body = res.json();
        if (body && body.timing && body.timing.elapsed_ms !== undefined) {
          elapsed = parseFloat(body.timing.elapsed_ms);
        }
      } catch (err) {
        // ignore parse errors
      }
    }
    if (elapsed !== null && Number.isFinite(elapsed)) {
      serverElapsed.add(elapsed, { mode });
    }
  }
}

function pickMetric(data, base, mode) {
  const key = `${base}{mode:${mode}}`;
  return data.metrics[key] || null;
}

function summaryPercentiles(metric) {
  if (!metric || !metric.values) {
    return null;
  }
  return {
    p50: metric.values['p(50)'],
    p90: metric.values['p(90)'],
    p95: metric.values['p(95)'],
    p99: metric.values['p(99)'],
  };
}

export function handleSummary(data) {
  if (!OUT_JSON) {
    return {};
  }

  const modes = ['async', 'sync'];
  const perMode = {};
  for (const mode of modes) {
    perMode[mode] = {
      http_req_duration: summaryPercentiles(pickMetric(data, 'http_req_duration', mode)),
      server_elapsed_ms: summaryPercentiles(pickMetric(data, 'server_elapsed_ms', mode)),
    };
  }

  const out = {
    timestamp: new Date().toISOString(),
    overall: {
      http_req_duration: data.metrics.http_req_duration?.values || {},
      server_elapsed_ms: data.metrics.server_elapsed_ms?.values || {},
      http_req_failed: data.metrics.http_req_failed?.values || {},
      http_reqs: data.metrics.http_reqs?.values || {},
    },
    per_mode: perMode,
    rps: data.metrics.http_reqs?.values?.rate || 0,
    error_rate: data.metrics.http_req_failed?.values?.rate || 0,
  };

  return {
    [OUT_JSON]: JSON.stringify(out, null, 2),
  };
}
