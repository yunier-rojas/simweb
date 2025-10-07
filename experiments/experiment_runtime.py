from simweb.entities import ServerMode, RecordField
from simweb.experiment import run_experiments
from simweb.files import load_csv, save_figures, load_styles
from simweb.metrics import compute_group_metrics
from simweb.report import generate_line_charts, generate_bar_charts

file_name = "experiment_runtime.csv"
html_name = "experiment_runtime.html"
all_df = load_csv(file_name)

RUNTIMES = {
    "Rust": 1.10,
    "Java": 1.87,
    "C#": 1.91,
    "JavaScript": 2.55,
    "CPython": 117.3,
}
BASE_CPU_MEAN_MS = 10.0

CPU_PERCENTS = [
    (l, BASE_CPU_MEAN_MS * v / 200.0 * 100) for l, v in RUNTIMES.items()
]

if all_df is None:
    all_df = run_experiments(
        modes=[ServerMode.sync_mode, ServerMode.async_mode],
        thread_count=3,
        cpu_percents=CPU_PERCENTS,
        io_means=[100.0],
        rates=[50.0],
        io_limits=[64],
        queue_limits=[64],
        timeouts=[1000.0],
        sim_time_ms=60_000.0,
        warmup_ms=10_000.0,
        seed=42,
        iterations=10,
    )
    all_df.write_csv(file_name)

layout, traces = load_styles("lines.yaml")
agg_df = compute_group_metrics(all_df, group_by=[RecordField.MODE, RecordField.LABEL_CPU])
runtime_order = [item[0] for item in sorted(RUNTIMES.items(), key=lambda x: x[1])]

figs = generate_bar_charts(
    agg_df,
    x=RecordField.LABEL_CPU,
    label="Runtime",
    column_order=runtime_order,
    layout=layout,
)
save_figures(figs, html_name)
