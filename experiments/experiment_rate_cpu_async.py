from simweb.entities import ServerMode, RecordField
from simweb.experiment import run_experiments
from simweb.files import load_csv, load_styles, save_figures
from simweb.metrics import compute_group_metrics
from simweb.report import generate_heatmap_charts

file_name = "experiment_rate_cpu_async.csv"
html_name = "experiment_rate_cpu_async.html"
all_df = load_csv(file_name)

ARRIVAL_RATES = [5 * n for n in range(1,  20)]
CPU_PERCENTS = [5 * n for n in range(1,  20)]

if all_df is None:
    all_df = run_experiments(
        modes=[ServerMode.async_mode],
        thread_count=3,
        cpu_percents=CPU_PERCENTS,
        io_means=[100.0],
        rates=ARRIVAL_RATES,
        io_limits=[64],
        queue_limits=[64],
        timeouts=[1000.0],
        sim_time_ms=60_000.0,
        warmup_ms=10_000.0,
        seed=42,
        iterations=10,
    )
    all_df.write_csv(file_name)


layout, traces = load_styles("heatmap.yaml")
agg_df = compute_group_metrics(all_df, group_by=[RecordField.LABEL_RATE, RecordField.LABEL_CPU])

figs = generate_heatmap_charts(
    agg_df,
    title="Async",
    x=RecordField.LABEL_RATE,
    x_label="Req/s",
    y=RecordField.LABEL_CPU,
    y_label="CPU vs I/O %",
    facet=None,
    layout=layout,
)
save_figures(figs, html_name)
