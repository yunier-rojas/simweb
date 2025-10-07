from simweb.entities import ServerMode, RecordField
from simweb.experiment import run_experiments
from simweb.files import load_csv, save_figures, load_styles
from simweb.metrics import compute_group_metrics
from simweb.report import generate_line_charts

file_name = "experiment_rate.csv"
html_name = "experiment_rate.html"
all_df = load_csv(file_name)

ARRIVAL_RATES = [5 * n for n in range(1,  20)]

if all_df is None:
    all_df = run_experiments(
        modes=[ServerMode.sync_mode, ServerMode.async_mode],
        thread_count=3,
        cpu_percents=[15],
        io_means=[100.0],
        rates=ARRIVAL_RATES,
        io_limits=[64],
        queue_limits=[64],
        timeouts=[1000.0],
        sim_time_ms=600_000.0,
        warmup_ms=10_000.0,
        seed=42,
        iterations=10,
    )
    all_df.write_csv(file_name)


layout, traces = load_styles("lines.yaml")
agg_df = compute_group_metrics(all_df, group_by=[RecordField.MODE, RecordField.LABEL_RATE])

figs = generate_line_charts(
    agg_df,
    x=RecordField.LABEL_RATE,
    label="Req/s",
    layout=layout,
    traces=traces,
)
save_figures(figs, html_name)
