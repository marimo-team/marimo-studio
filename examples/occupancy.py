# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo==0.24.0",
#     "polars==1.33.1",
# ]
#
# [tool.marimo-studio]
# default = "monitor"
# preserve_session = false
# runtime = "server"
# runtimes = ["server", "wasm"]
# show_cell_logs = false
#
# [tool.marimo-studio.cells]
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium", app_title="Building Occupancy")


@app.cell(hide_code=True)
def introduction(mo):
    mo.md("""
    # Building Occupancy

    Environmental readings from Room 01 cover temperature, humidity, light,
    carbon dioxide, and observed occupancy. Sensor deviations are measured
    against rolling baselines, and a transparent occupancy score is evaluated
    across thresholds.
    """)
    return


@app.cell
def _():
    import io
    import urllib.request

    import marimo as mo
    import polars as pl

    return io, mo, pl, urllib


@app.cell(hide_code=True)
def data_context(mo):
    mo.md("""
    ## Room observations

    The training split comes from Luis Candanedo's
    [UCI Occupancy Detection dataset](https://doi.org/10.24432/C5X01N), order
    the observations, and retain the reported physical units. The dataset is
    licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
    """)
    return


@app.cell
def load_readings(io, pl, urllib):
    source_url = (
        "https://raw.githubusercontent.com/holoviz/panel/"
        "62dda3f986251295ab4892a45e02c7f1533cf4c0/examples/assets/occupancy.csv"
    )
    with urllib.request.urlopen(source_url) as response:
        source = io.BytesIO(response.read())
    readings = pl.read_csv(source, try_parse_dates=True).sort("date")
    readings.head(8)
    return (readings,)


@app.cell(hide_code=True)
def monitor_context(mo):
    mo.md("""
    ## Environmental signal

    Select a physical measure to compare its full history with a rolling
    baseline and the resulting anomaly candidates.
    """)
    return


@app.cell
def metric_control(mo):
    metric = mo.ui.dropdown(
        options=["CO2", "Light", "Temperature", "Humidity"],
        value="CO2",
        label="Signal",
    )
    metric
    return (metric,)


@app.cell
def sensor_analysis(metric, pl, readings):
    selected_sensor_series = (
        readings.select(
            "date",
            "Occupancy",
            pl.lit(metric.value).alias("metric"),
            pl.col(metric.value).cast(pl.Float32).alias("value"),
        )
        .with_columns(
            pl.col("value")
            .rolling_mean(window_size=60, min_samples=12)
            .alias("baseline")
        )
        .with_columns((pl.col("value") - pl.col("baseline")).abs().alias("deviation"))
        .with_columns(
            pl.col("deviation")
            .rolling_quantile(0.95, window_size=120, min_samples=24)
            .alias("limit")
        )
        .with_columns(
            (pl.col("deviation") > pl.col("limit")).fill_null(False).alias("anomaly")
        )
        .select("date", "Occupancy", "metric", "value", "baseline", "anomaly")
    )
    current_window = selected_sensor_series.tail(180)
    occupancy_summary = {
        "observations": readings.height,
        "occupied": readings.select(pl.col("Occupancy").sum()).item(),
        "occupancy_rate": readings.select(pl.col("Occupancy").mean()).item(),
        "metric": metric.value,
        "anomalies": selected_sensor_series.filter(pl.col("anomaly")).height,
    }
    current_window.tail(8)
    return occupancy_summary, selected_sensor_series


@app.cell(hide_code=True)
def model_context(mo):
    mo.md("""
    ## Occupancy score

    A transparent score combines normalized light and CO2 readings. The
    threshold control exposes the in-sample precision and recall tradeoff while
    each component of the calculation remains explicit.
    """)
    return


@app.cell
def threshold_control(mo):
    threshold = mo.ui.slider(
        start=0.1,
        stop=0.9,
        step=0.05,
        value=0.5,
        label="Occupancy threshold",
        show_value=True,
    )
    threshold
    return (threshold,)


@app.cell
def score_model(pl, readings, threshold):
    light_max = readings.select(pl.col("Light").quantile(0.99)).item()
    co2_min = readings["CO2"].min()
    co2_max = readings.select(pl.col("CO2").quantile(0.99)).item()
    scored = readings.with_columns(
        pl.col("Light").clip(0, light_max).truediv(light_max).alias("light_score"),
        (
            (pl.col("CO2").clip(co2_min, co2_max) - co2_min).truediv(
                max(co2_max - co2_min, 1.0)
            )
        ).alias("co2_score"),
    ).with_columns(
        (0.7 * pl.col("light_score") + 0.3 * pl.col("co2_score"))
        .cast(pl.Float32)
        .alias("score")
    )

    def evaluate(_threshold):
        _rows = scored.with_columns((pl.col("score") >= _threshold).alias("predicted"))
        _tp = _rows.filter(pl.col("predicted") & (pl.col("Occupancy") == 1)).height
        _tn = _rows.filter(~pl.col("predicted") & (pl.col("Occupancy") == 0)).height
        _fp = _rows.filter(pl.col("predicted") & (pl.col("Occupancy") == 0)).height
        _fn = _rows.filter(~pl.col("predicted") & (pl.col("Occupancy") == 1)).height
        return {
            "threshold": _threshold,
            "accuracy": (_tp + _tn) / scored.height,
            "precision": _tp / max(_tp + _fp, 1),
            "recall": _tp / max(_tp + _fn, 1),
            "true_positive": _tp,
            "true_negative": _tn,
            "false_positive": _fp,
            "false_negative": _fn,
        }

    thresholds = [round(0.1 + 0.05 * index, 2) for index in range(17)]
    threshold_metrics = pl.DataFrame(
        [evaluate(_threshold) for _threshold in thresholds]
    )
    model_summary = evaluate(threshold.value)
    prediction_rows = (
        scored.with_columns(
            (pl.col("score") >= threshold.value).cast(pl.Int8).alias("predicted")
        )
        .with_columns(
            pl.when((pl.col("predicted") == 1) & (pl.col("Occupancy") == 1))
            .then(pl.lit("true positive"))
            .when((pl.col("predicted") == 0) & (pl.col("Occupancy") == 0))
            .then(pl.lit("true negative"))
            .when((pl.col("predicted") == 1) & (pl.col("Occupancy") == 0))
            .then(pl.lit("false positive"))
            .otherwise(pl.lit("false negative"))
            .cast(pl.Categorical)
            .alias("outcome")
        )
        .select(
            "date",
            "Temperature",
            "Humidity",
            "Light",
            "CO2",
            "Occupancy",
            "score",
            "predicted",
            "outcome",
        )
    )
    error_cases = prediction_rows.filter(
        pl.col("Occupancy") != pl.col("predicted")
    ).head(120)
    threshold_metrics
    return error_cases, model_summary, threshold_metrics


@app.cell(hide_code=True)
def conclusion(mo, model_summary, occupancy_summary):
    mo.md(
        f"""
        ## Operational reading

        The source records occupancy for **{occupancy_summary["occupancy_rate"]:.1%}**
        of observations. At a threshold of **{model_summary["threshold"]:.2f}**,
        the transparent score reaches **{model_summary["accuracy"]:.1%}
        in-sample accuracy** and **{model_summary["recall"]:.1%} in-sample
        recall** on the training readings.
        """
    )
    return


if __name__ == "__main__":
    app.run()
