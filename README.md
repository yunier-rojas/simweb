# **simweb** – Sync & Async Webserver Simulation

**simweb** is a **discrete-event simulation** (built on [SimPy](https://simpy.readthedocs.io/)) for comparing **synchronous (thread-per-request)** and **asynchronous (event loop)** server models.

It helps explore how **async** and **async** processes behave under different workloads and how they impact the **four golden signals** from [Google SRE](https://sre.google/sre-book/monitoring-distributed-systems/):

* **Throughput** – requests per second
* **Latency** – p95 / p99
* **Success Rate** – completed requests (%)


---

## 🔍 Why Simulation

Benchmarking real systems is **slow and inconsistent**:

* Real workloads are hard to reproduce.
* Synthetic ones are too simple.
* Hardware, kernel, or network differences skew results.

Simulation offers:

* **Fast iteration** (seconds, not hours)
* **Controlled variables** (CPU%, IO wait, rate, timeouts)
* **Fair sync vs async comparison** under identical load
* **Educational clarity** — run designed scenarios in isolated environments

---

## ⚙️ Models

### Web Worker

**Sync**

* Multiple threads (≈2–4 per core)
* Threads block during IO
* Worker pool size = thread count

**Async**

* Single-threaded event loop
* CPU work blocks, IO waits release
* Worker pool size = 1

### Pipeline

1. Clients generate requests (Poisson or bursty)
2. Admission gate enforces queue limit
3. Worker pool runs service logic (CPU → IO → CPU)
4. Timeouts stop long requests
5. Records include arrival, finish, latency, status, CPU time

---

## 📊 Metrics

### Group metrics

Aggregate by experiment parameters (e.g. mode, rate, CPU%).

* Throughput = completed / wall time
* Success rate = % completed
* Latency = pooled p95/p99

### Time metrics

Aggregate in time bins (default 1s) to show golden signals over time — ideal for spotting transient effects like queue buildup.


---

## 🧪 Run Experiments

```bash
python experiments/experiment_cpu_rate.py
```

Generates:

* `report_cpu_rate.csv` – raw results
* `report_cpu_rate.html` – plots (heatmaps, line charts)

### Time-series dashboard

```bash
python experiments/dashboard.py
```

Outputs:

* `dashboard.html` – golden metrics over time

---

## 🧩 Assumptions

* 1 process per core
* Sync: 2–4 threads/core
* Async: 1 event loop/core
* CPU split between pre/post IO
* IO + CPU ~ exponential or log-normal
* Arrivals ~ Poisson (bursty optional)

---

## ⚠️ Limitations

* Not a real benchmark — **illustrative only**
* Ignores hardware and OS-level effects
* Single process only
* Perfect async assumed

---

## 🖼️ Architecture

### Sync

![Sync process](https://img.plantuml.biz/plantuml/png/NP6nRiCm34HtVGMHgHto0nwA62bQU7AXfl2isZS8aIM5efFVhsJ7Q9n10dZlH1wXGnB3CerEcLu2qz5PU54nYxQtqNYXNSrihyRjo2IgjqZZCY79ZFGMTO7Fu3IZRekQTbQRLgbb7ktVgAxe4nvi1CHBMsMSqCVad2AgYsTnL_JE8Igu1Ahx7b4mh0vTqNVPADUwr5sLBPV9CkWs1rf1DXw_VYWoLgLfgtpePgpGowyB_Hd3QuPPszyVX34w29vxX5JcbR0dEo9CfRfRriJ_O8xzqEd9g95YyAaG-E5X3Gq7a_MY7lAL_-mF "Sync")

[Open in PlantUML Editor](https://editor.plantuml.com/uml/NP6nRiCm34HtVGMHgHto0nwA62bQU7AXfl2isZS8aIM5efFVhsJ7Q9n10dZlH1wXGnB3CerEcLu2qz5PU54nYxQtqNYXNSrihyRjo2IgjqZZCY79ZFGMTO7Fu3IZRekQTbQRLgbb7ktVgAxe4nvi1CHBMsMSqCVad2AgYsTnL_JE8Igu1Ahx7b4mh0vTqNVPADUwr5sLBPV9CkWs1rf1DXw_VYWoLgLfgtpePgpGowyB_Hd3QuPPszyVX34w29vxX5JcbR0dEo9CfRfRriJ_O8xzqEd9g95YyAaG-E5X3Gq7a_MY7lAL_-mF)


### Async


![Async process](https://img.plantuml.biz/plantuml/png/RL7BJiGW5Dtp5JUpdn_emWpfHDDL3Mgw9fsp859WBhVw-m9rrAeB2ETn3uTmoc9PriKhEqjawhr349KAwMQNR10wQ6RtPls1R2QzbmokAx8qoUobAV8hE3Tfsal3sDXXL6gxZuvtf3jwG01R0V4MgwmNkb-zLqIwUZPtHsUEIS5da9vd9C7bvZ0TFTKN5MmgdZhg7ryeCNum1XusVp73s9L5xzRLiN8wRa7d6F0x9-RggRsUtOAuLlHfkPNx5bh3FYx9G_3NQ91J3Aq7mkMVVfKzbQrypmS0 "Async")

[Open in PlantUML Editor](https://editor.plantuml.com/uml/RL7BJiGW5Dtp5JUpdn_emWpfHDDL3Mgw9fsp859WBhVw-m9rrAeB2ETn3uTmoc9PriKhEqjawhr349KAwMQNR10wQ6RtPls1R2QzbmokAx8qoUobAV8hE3Tfsal3sDXXL6gxZuvtf3jwG01R0V4MgwmNkb-zLqIwUZPtHsUEIS5da9vd9C7bvZ0TFTKN5MmgdZhg7ryeCNum1XusVp73s9L5xzRLiN8wRa7d6F0x9-RggRsUtOAuLlHfkPNx5bh3FYx9G_3NQ91J3Aq7mkMVVfKzbQrypmS0)

---

## 🚀 Roadmap

* [ ] Combine multiple arrival distributions.

---

## 🤝 Contributing

Ideas welcome:

* More arrival distributions
* More service time models
* Real workload traces as input
* Would it be possible to add saturation?

---

## 📜 License

**Apache 2.0**
