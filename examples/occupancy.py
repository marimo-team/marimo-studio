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

    We load the training split from Luis Candanedo's
    [UCI Occupancy Detection dataset](https://doi.org/10.24432/C5X01N), order
    the observations by timestamp, and retain the reported physical units. The
    dataset is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
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
def scope_context(mo):
    mo.md("""
    ## Observation scope

    Choose the slice of room activity used by every analysis below. The sensor
    history, room profiles, model evidence, and published views recompute from
    the same selected observations.
    """)
    return


@app.cell
def analysis_scope_control(mo):
    analysis_scope = mo.ui.dropdown(
        options={
            "Complete record": "all",
            "Weekdays · 07:00–19:00": "operating-hours",
            "Off-hours + weekends": "off-hours",
        },
        value="Complete record",
        label="Observation scope",
    )
    analysis_scope
    return (analysis_scope,)


@app.cell
def select_observations(analysis_scope, pl, readings):
    _operating_hours = (
        (pl.col("date").dt.weekday() <= 5)
        & (pl.col("date").dt.hour() >= 7)
        & (pl.col("date").dt.hour() < 19)
    )
    if analysis_scope.value == "operating-hours":
        scoped_readings = readings.filter(_operating_hours)
        scope_label = "Weekdays · 07:00–19:00"
    elif analysis_scope.value == "off-hours":
        scoped_readings = readings.filter(~_operating_hours)
        scope_label = "Off-hours + weekends"
    else:
        scoped_readings = readings
        scope_label = "Complete record"
    scoped_readings.head(8)
    return scope_label, scoped_readings


@app.cell(hide_code=True)
def monitor_context(mo):
    mo.md("""
    ## Environmental signal

    Select a physical measure to compare its history in the current observation
    scope with a rolling baseline and the resulting anomaly candidates.
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
def sensor_analysis(metric, pl, scope_label, scoped_readings):
    selected_sensor_series = (
        scoped_readings.select(
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
    _occupied_readings = scoped_readings.select(pl.col("Occupancy").sum()).item()
    _reading_interval_minutes = scoped_readings.select(
        pl.col("date").diff().dt.total_seconds().median() / 60
    ).item()
    occupancy_summary = {
        "room": "Room 01",
        "scope_label": scope_label,
        "period_start": scoped_readings["date"].min().strftime("%Y-%m-%d %H:%M"),
        "period_end": scoped_readings["date"].max().strftime("%Y-%m-%d %H:%M"),
        "observations": scoped_readings.height,
        "occupied": _occupied_readings,
        "occupancy_rate": scoped_readings.select(pl.col("Occupancy").mean()).item(),
        "reading_interval_minutes": float(_reading_interval_minutes),
        "estimated_occupied_hours": float(
            _occupied_readings * _reading_interval_minutes / 60
        ),
        "metric": metric.value,
        "anomalies": selected_sensor_series.filter(pl.col("anomaly")).height,
    }
    current_window.tail(8)
    return occupancy_summary, selected_sensor_series


@app.cell(hide_code=True)
def room_profile_context(mo):
    mo.md("""
    ## Room use profiles

    Aggregate the readings by hour and day, then compare environmental
    conditions recorded while the room was occupied and vacant.
    """)
    return


@app.cell
def room_profiles(pl, scoped_readings):
    hourly_room_profile = (
        scoped_readings.group_by_dynamic("date", every="1h")
        .agg(
            pl.col("Occupancy").mean().alias("occupancy_rate"),
            pl.col("CO2").mean().alias("co2"),
            pl.col("Temperature").mean().alias("temperature"),
            pl.col("Humidity").mean().alias("humidity"),
            pl.col("Light").mean().alias("light"),
        )
        .with_columns(
            pl.col("date").dt.strftime("%Y-%m-%dT%H:%M:%S").alias("timestamp")
        )
        .select(
            "timestamp", "occupancy_rate", "co2", "temperature", "humidity", "light"
        )
    )
    daily_room_profile = (
        scoped_readings.with_columns(
            pl.col("date").dt.strftime("%Y-%m-%d").alias("day")
        )
        .group_by("day")
        .agg(
            pl.len().alias("observations"),
            pl.col("Occupancy").sum().alias("occupied"),
            pl.col("Occupancy").mean().alias("occupancy_rate"),
            pl.col("CO2").mean().alias("mean_co2"),
            pl.col("CO2").max().alias("peak_co2"),
            pl.col("Temperature").mean().alias("mean_temperature"),
        )
        .sort("day")
    )
    daily_occupancy_peak = daily_room_profile.sort(
        ["occupancy_rate", "day"], descending=[True, False]
    ).row(0, named=True)

    _sensor_profile_rows = []
    for _column, _label, _unit in (
        ("CO2", "Carbon dioxide", "ppm"),
        ("Light", "Light", "lux"),
        ("Temperature", "Temperature", "°C"),
        ("Humidity", "Humidity", "%"),
    ):
        _vacant = scoped_readings.filter(pl.col("Occupancy") == 0)[_column].mean()
        _occupied = scoped_readings.filter(pl.col("Occupancy") == 1)[_column].mean()
        _minimum = scoped_readings[_column].min()
        _maximum = scoped_readings[_column].max()
        _sensor_profile_rows.append(
            {
                "key": _column,
                "label": _label,
                "unit": _unit,
                "vacant": float(_vacant),
                "occupied": float(_occupied) if _occupied is not None else None,
                "minimum": float(_minimum),
                "maximum": float(_maximum),
                "relative_separation": (
                    abs(float(_occupied) - float(_vacant))
                    / max(float(_maximum) - float(_minimum), 1.0)
                    if _occupied is not None
                    else None
                ),
            }
        )
    sensor_profiles = pl.DataFrame(_sensor_profile_rows)
    _available_sensor_separations = sensor_profiles.filter(
        pl.col("relative_separation").is_not_null()
    )
    sensor_separation_peak = (
        _available_sensor_separations.sort("relative_separation", descending=True).row(
            0, named=True
        )
        if _available_sensor_separations.height
        else None
    )

    daily_room_profile
    return (
        daily_occupancy_peak,
        daily_room_profile,
        hourly_room_profile,
        sensor_profiles,
        sensor_separation_peak,
    )


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
def score_model(pl, scoped_readings, threshold):
    light_max = scoped_readings.select(pl.col("Light").quantile(0.99)).item()
    co2_min = scoped_readings["CO2"].min()
    co2_max = scoped_readings.select(pl.col("CO2").quantile(0.99)).item()
    scored = scoped_readings.with_columns(
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
    model_summary = {
        **evaluate(threshold.value),
        "normalization": {
            "light_min": 0.0,
            "light_max": float(light_max),
            "co2_min": float(co2_min),
            "co2_max": float(co2_max),
        },
    }
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
    ranked_model_errors = (
        prediction_rows.filter(pl.col("Occupancy") != pl.col("predicted"))
        .with_columns(
            (pl.col("score") - model_summary["threshold"]).abs().alias("distance")
        )
        .sort("distance", descending=True)
    )
    threshold_metrics
    return model_summary, ranked_model_errors, threshold_metrics


@app.cell
def occupancy_analysis_snapshot(
    analysis_scope,
    daily_occupancy_peak,
    daily_room_profile,
    hourly_room_profile,
    model_summary,
    occupancy_summary,
    pl,
    ranked_model_errors,
    sensor_separation_peak,
    sensor_profiles,
    threshold_metrics,
):
    occupancy_analysis = {
        "selection": {
            "scope": analysis_scope.value,
            "metric": occupancy_summary["metric"],
            "threshold": model_summary["threshold"],
        },
        "summary": occupancy_summary,
        "hourly_room_profile": hourly_room_profile.to_dicts(),
        "daily_room_profile": daily_room_profile.to_dicts(),
        "sensor_profiles": sensor_profiles.to_dicts(),
        "profile_summary": {
            "highest_occupancy_day": daily_occupancy_peak,
            "widest_sensor_separation": sensor_separation_peak,
        },
        "model": {
            **model_summary,
            "curve": threshold_metrics.to_dicts(),
            "errors": ranked_model_errors.with_columns(
                pl.col("date").dt.strftime("%Y-%m-%dT%H:%M:%S")
            ).to_dicts(),
        },
    }
    occupancy_analysis["summary"]
    return (occupancy_analysis,)


@app.cell(hide_code=True)
def conclusion(mo, model_summary, occupancy_summary):
    _recall_reading = (
        f"**{model_summary['recall']:.1%} in-sample recall**"
        if occupancy_summary["occupied"]
        else "**recall unavailable because this scope contains no occupied observations**"
    )
    mo.md(
        f"""
        ## Operational reading

        The source records occupancy for **{occupancy_summary["occupancy_rate"]:.1%}**
        of observations. At a threshold of **{model_summary["threshold"]:.2f}**,
        the transparent score reaches **{model_summary["accuracy"]:.1%}
        in-sample accuracy**, with {_recall_reading} on the selected readings.
        """
    )
    return


if __name__ == "__main__":
    app.run()
