from simweb.entities import ServerMode, RecordField
from simweb.experiment import run_experiments
from simweb.files import load_csv, save_figures, load_styles
from simweb.metrics import compute_time_metrics
from simweb.report import generate_time_charts

file_name = "dashboard.csv"
html_name = "dashboard.html"
all_df = load_csv(file_name)

if all_df is None:
    all_df = run_experiments(
        modes=[ServerMode.sync_mode, ServerMode.async_mode],
        thread_count=3,
        cpu_percents=[30.0],
        io_means=[100.0],
        rates=[70.0],
        io_limits=[64],
        queue_limits=[64],
        timeouts=[1000.0],
        sim_time_ms=3_600_000.0,
        warmup_ms=1000.0,
        seed=42,
        iterations=1,
    )
    all_df.write_csv(file_name)


layout, traces = load_styles("lines.yaml")
agg_df = compute_time_metrics(all_df, group_by=[RecordField.MODE], bin_ms=60_000.0)
figs = generate_time_charts(agg_df, layout=layout, traces=traces)

save_figures(figs, html_name)
