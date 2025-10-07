from plotly.graph_objs import Figure
import yaml
import polars as pl


def load_csv(csv_path) -> pl.LazyFrame | None:
    try:
        return pl.read_csv(csv_path)
    except FileNotFoundError:
        return None


def save_figures(figs: list[Figure], save_path: str):
    with open(save_path, "w", encoding="utf-8") as f:
        for idx, fig in enumerate(figs):
            f.write(
                fig.to_html(
                    full_html=False, include_plotlyjs="cdn" if idx == 0 else None
                )
            )


def load_styles(style_path: str) -> tuple[dict, dict]:
    with open(style_path, "r") as f:
        cfg = yaml.safe_load(f)

    # Get layout and trace configs
    layout = cfg.get("layout", {})
    traces = cfg.get("traces", {})

    return layout, traces
