# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo>=0.24.0",
#     "matplotlib>=3.10.8",
#     "numpy>=2.4.3",
#     "polars>=1.33.1",
# ]
#
# [tool.marimo-studio]
# default = "monitor"
# preserve_session = false
# runtime = "server"
# runtimes = ["server", "wasm", "zero-python"]
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
    import matplotlib
    import numpy as np
    import polars as pl
    from matplotlib.figure import Figure

    return Figure, io, matplotlib, mo, np, pl, urllib


@app.cell
def analysis_parameters():
    occupancy_parameters = {
        "monitor": {
            "anomaly_min_samples": 24,
            "anomaly_quantile": 0.95,
            "anomaly_window": 120,
            "baseline_min_samples": 12,
            "baseline_window": 60,
        },
        "model": {
            "co2_weight": 0.3,
            "default_threshold": 0.5,
            "light_weight": 0.7,
            "normalization_quantile": 0.99,
            "threshold_maximum": 0.9,
            "threshold_minimum": 0.1,
            "threshold_step": 0.05,
        },
    }
    return (occupancy_parameters,)


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

    Choose the slice of room activity that every section below analyzes.
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
        label="Scope",
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


@app.cell
def summarize_scope(pl, scope_label, scoped_readings):
    _occupied_readings = scoped_readings.select(pl.col("Occupancy").sum()).item()
    _reading_interval_minutes = scoped_readings.select(
        pl.col("date").diff().dt.total_seconds().median() / 60
    ).item()
    scope_summary = {
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
    }
    return (scope_summary,)


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
def sensor_analysis(metric, occupancy_parameters, pl, scope_summary, scoped_readings):
    _monitor = occupancy_parameters["monitor"]
    selected_sensor_series = (
        scoped_readings.select(
            "date",
            "Occupancy",
            pl.lit(metric.value).alias("metric"),
            pl.col(metric.value).cast(pl.Float32).alias("value"),
        )
        .with_columns(
            pl.col("value")
            .rolling_mean(
                window_size=_monitor["baseline_window"],
                min_samples=_monitor["baseline_min_samples"],
            )
            .alias("baseline")
        )
        .with_columns((pl.col("value") - pl.col("baseline")).abs().alias("deviation"))
        .with_columns(
            pl.col("deviation")
            .rolling_quantile(
                _monitor["anomaly_quantile"],
                window_size=_monitor["anomaly_window"],
                min_samples=_monitor["anomaly_min_samples"],
            )
            .alias("limit")
        )
        .with_columns(
            (pl.col("deviation") > pl.col("limit")).fill_null(False).alias("anomaly")
        )
        .select("date", "Occupancy", "metric", "value", "baseline", "anomaly")
    )
    current_window = selected_sensor_series.tail(180)
    occupancy_summary = {
        **scope_summary,
        "metric": metric.value,
        "anomalies": selected_sensor_series.filter(pl.col("anomaly")).height,
        "monitor": _monitor,
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
def threshold_control(mo, occupancy_parameters):
    _model = occupancy_parameters["model"]
    threshold = mo.ui.slider(
        start=_model["threshold_minimum"],
        stop=_model["threshold_maximum"],
        step=_model["threshold_step"],
        value=_model["default_threshold"],
        label="Occupancy threshold",
        show_value=True,
    )
    threshold
    return (threshold,)


@app.cell
def model_sweep(occupancy_parameters, pl, scoped_readings):
    _model = occupancy_parameters["model"]
    light_max = scoped_readings.select(
        pl.col("Light").quantile(_model["normalization_quantile"])
    ).item()
    co2_min = scoped_readings["CO2"].min()
    co2_max = scoped_readings.select(
        pl.col("CO2").quantile(_model["normalization_quantile"])
    ).item()
    scored = scoped_readings.with_columns(
        pl.col("Light").clip(0, light_max).truediv(light_max).alias("light_score"),
        (
            (pl.col("CO2").clip(co2_min, co2_max) - co2_min).truediv(
                max(co2_max - co2_min, 1.0)
            )
        ).alias("co2_score"),
    ).with_columns(
        (
            _model["light_weight"] * pl.col("light_score")
            + _model["co2_weight"] * pl.col("co2_score")
        )
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

    def error_evidence(_threshold):
        _prediction_rows = (
            scored.with_columns(
                (pl.col("score") >= _threshold).cast(pl.Int8).alias("predicted")
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
        return (
            _prediction_rows.filter(pl.col("Occupancy") != pl.col("predicted"))
            .with_columns(
                (pl.col("score") - _threshold).abs().alias("distance"),
                pl.col("date").dt.strftime("%Y-%m-%dT%H:%M:%S"),
            )
            .sort("distance", descending=True)
        )

    _threshold_steps = int(
        round(
            (_model["threshold_maximum"] - _model["threshold_minimum"])
            / _model["threshold_step"]
        )
    )
    thresholds = [
        round(
            _model["threshold_minimum"] + _model["threshold_step"] * index,
            2,
        )
        for index in range(_threshold_steps + 1)
    ]
    threshold_metrics = pl.DataFrame(
        [evaluate(_threshold) for _threshold in thresholds]
    )
    model_evidence = [
        {
            **evaluate(_threshold),
            "errors": error_evidence(_threshold).head(14).to_dicts(),
        }
        for _threshold in thresholds
    ]
    model_normalization = {
        "light_min": 0.0,
        "light_max": float(light_max),
        "co2_min": float(co2_min),
        "co2_max": float(co2_max),
    }
    threshold_metrics
    return model_evidence, model_normalization, scored, threshold_metrics


@app.cell
def selected_model(model_normalization, pl, scored, threshold):
    model_summary = {
        "threshold": threshold.value,
        "normalization": model_normalization,
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
    _true_positive = prediction_rows.filter(
        (pl.col("predicted") == 1) & (pl.col("Occupancy") == 1)
    ).height
    _true_negative = prediction_rows.filter(
        (pl.col("predicted") == 0) & (pl.col("Occupancy") == 0)
    ).height
    _false_positive = prediction_rows.filter(
        (pl.col("predicted") == 1) & (pl.col("Occupancy") == 0)
    ).height
    _false_negative = prediction_rows.filter(
        (pl.col("predicted") == 0) & (pl.col("Occupancy") == 1)
    ).height
    model_summary.update(
        {
            "accuracy": (_true_positive + _true_negative) / prediction_rows.height,
            "precision": _true_positive / max(_true_positive + _false_positive, 1),
            "recall": _true_positive / max(_true_positive + _false_negative, 1),
            "true_positive": _true_positive,
            "true_negative": _true_negative,
            "false_positive": _false_positive,
            "false_negative": _false_negative,
        }
    )
    return model_summary, ranked_model_errors


@app.cell
def score_baselines(pl, scored, threshold_metrics):
    # The best accuracy each normalized signal reaches alone, over the same
    # thresholds, beside the weighted score's.
    def _best_accuracy(column):
        return max(
            scored.select(
                ((pl.col(column) >= _threshold) == (pl.col("Occupancy") == 1)).mean()
            ).item()
            for _threshold in threshold_metrics["threshold"]
        )

    score_baselines = {
        "light": _best_accuracy("light_score"),
        "co2": _best_accuracy("co2_score"),
        "score": _best_accuracy("score"),
    }
    score_baselines
    return (score_baselines,)


@app.cell
def occupancy_analysis_snapshot(
    analysis_scope,
    daily_occupancy_peak,
    daily_room_profile,
    hourly_room_profile,
    model_evidence,
    model_normalization,
    occupancy_parameters,
    sensor_separation_peak,
    sensor_profiles,
    scope_summary,
):
    occupancy_analysis = {
        "selection": {
            "scope": analysis_scope.value,
        },
        "summary": scope_summary,
        "hourly_room_profile": hourly_room_profile.to_dicts(),
        "daily_room_profile": daily_room_profile.to_dicts(),
        "sensor_profiles": sensor_profiles.to_dicts(),
        "profile_summary": {
            "highest_occupancy_day": daily_occupancy_peak,
            "widest_sensor_separation": sensor_separation_peak,
        },
        "model": {
            **occupancy_parameters["model"],
            "normalization": model_normalization,
            "evidence": model_evidence,
        },
    }
    occupancy_analysis["summary"]
    return (occupancy_analysis,)


@app.cell(hide_code=True)
def figures_context(mo):
    mo.md("""
    ## Figures

    These figures show the room over the scope, when it is used, how each
    sensor differs while it is occupied, and how the score trades accuracy
    against its threshold. Each sets its shape and a compact 7-point style, so
    a view can place it at any width.
    """)
    return


@app.cell
def figure_style():
    INK = "#102126"
    SLATE = "#3d5761"
    FOG = "#677b82"
    MIST = "#dfe8ec"
    SIGNAL = "#fa4e1d"
    figure_style = {
        "font.size": 7,
        "axes.edgecolor": FOG,
        "axes.labelcolor": SLATE,
        "axes.linewidth": 0.5,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "axes.titlecolor": INK,
        "axes.titlelocation": "left",
        "axes.titlesize": "medium",
        "axes.titleweight": "bold",
        "legend.frameon": False,
        "xtick.color": FOG,
        "xtick.labelcolor": SLATE,
        "xtick.major.size": 2.5,
        "xtick.major.width": 0.5,
        "ytick.color": FOG,
        "ytick.labelcolor": SLATE,
        "ytick.major.size": 2.5,
        "ytick.major.width": 0.5,
    }
    return FOG, INK, MIST, SIGNAL, SLATE, figure_style


@app.cell
def room_timeline(
    Figure,
    FOG,
    INK,
    SIGNAL,
    SLATE,
    figure_style,
    matplotlib,
    np,
    pl,
    scoped_readings,
):
    _series = (
        scoped_readings.group_by_dynamic("date", every="10m")
        .agg(pl.col("CO2").mean(), pl.col("Light").mean(), pl.col("Occupancy").mean())
        .sort("date")
    )
    _dates = _series["date"].to_numpy()
    # Break the lines where the scope skips time, such as nights and weekends.
    _breaks = np.flatnonzero(np.diff(_dates) > np.timedelta64(30, "m")) + 1
    _dates = np.insert(_dates, _breaks, _dates[_breaks - 1])
    _occupied = np.insert(_series["Occupancy"].to_numpy() >= 0.5, _breaks, False)

    def _day(value, _position):
        day = matplotlib.dates.num2date(value)
        return f"{day:%a} {day.day} {day:%b}"

    with matplotlib.rc_context(figure_style):
        room_timeline = Figure(figsize=(6.5, 2.15), layout="constrained")
        _axes = room_timeline.subplots(2, 1, sharex=True)
        for _axis, _column, _label, _color in zip(
            _axes,
            ("CO2", "Light"),
            ("CO$_2$ (ppm)", "Light (lux)"),
            (INK, SLATE),
        ):
            _values = np.insert(_series[_column].to_numpy(), _breaks, np.nan)
            _axis.fill_between(
                _dates,
                0,
                1,
                where=_occupied,
                transform=_axis.get_xaxis_transform(),
                color=SIGNAL,
                alpha=0.13,
                linewidth=0,
                step="mid",
            )
            _axis.plot(_dates, _values, color=_color, linewidth=0.75)
            _axis.set_ylabel(_label)
            _axis.margins(x=0)
            _axis.grid(axis="y", color=FOG, alpha=0.18, linewidth=0.4)
        if _occupied.any():
            room_timeline.legend(
                handles=[
                    matplotlib.patches.Patch(
                        color=SIGNAL, alpha=0.13, label="Mostly occupied"
                    )
                ],
                loc="outside upper right",
            )
        # Ticks mark midnight, and each day's label sits at its noon.
        _axes[1].xaxis.set_major_locator(matplotlib.dates.DayLocator())
        _axes[1].xaxis.set_major_formatter(matplotlib.ticker.NullFormatter())
        _axes[1].xaxis.set_minor_locator(matplotlib.dates.HourLocator(byhour=12))
        _axes[1].xaxis.set_minor_formatter(matplotlib.ticker.FuncFormatter(_day))
        _axes[1].tick_params(axis="x", which="minor", length=0)
    room_timeline
    return (room_timeline,)


@app.cell
def occupancy_heatmap(
    Figure, MIST, SIGNAL, figure_style, matplotlib, np, pl, scoped_readings
):
    _cells = scoped_readings.group_by(
        pl.col("date").dt.weekday().alias("weekday"),
        pl.col("date").dt.hour().alias("hour"),
    ).agg(pl.col("Occupancy").mean().alias("rate"))
    _grid = np.full((7, 24), np.nan)
    for _row in _cells.iter_rows(named=True):
        _grid[_row["weekday"] - 1, _row["hour"]] = _row["rate"]
    _colors = matplotlib.colors.LinearSegmentedColormap.from_list(
        "occupancy", [MIST, SIGNAL]
    ).with_extremes(bad="white")
    with matplotlib.rc_context(figure_style):
        occupancy_heatmap = Figure(figsize=(3.5, 1.55), layout="constrained")
        _axis = occupancy_heatmap.subplots()
        _mesh = _axis.pcolormesh(
            np.ma.masked_invalid(_grid),
            cmap=_colors,
            vmin=0,
            vmax=1,
            edgecolors="white",
            linewidth=0.8,
        )
        _axis.invert_yaxis()
        # Hours label the edges of their cells, where each hour starts.
        _axis.set_xticks(
            np.arange(0, 25, 6), [f"{hour:02d}:00" for hour in range(0, 25, 6)]
        )
        _axis.set_yticks(
            np.arange(7) + 0.5, ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        )
        _axis.tick_params(length=0)
        for _side in _axis.spines.values():
            _side.set_visible(False)
        _bar = occupancy_heatmap.colorbar(_mesh, ax=_axis, fraction=0.04, pad=0.02)
        _bar.outline.set_visible(False)
        _bar.set_ticks([0, 0.5, 1], labels=["0%", "50%", "100%"])
        _bar.ax.tick_params(length=0)
    occupancy_heatmap
    return (occupancy_heatmap,)


@app.cell
def sensor_distributions(
    Figure,
    SIGNAL,
    SLATE,
    figure_style,
    matplotlib,
    np,
    pl,
    scoped_readings,
):
    with matplotlib.rc_context(figure_style):
        sensor_distributions = Figure(figsize=(7.1, 1.35), layout="constrained")
        _axes = sensor_distributions.subplots(1, 4)
        for _axis, (_column, _label) in zip(
            _axes,
            (
                ("CO2", "CO$_2$ (ppm)"),
                ("Light", "Light (lux)"),
                ("Temperature", "Temperature (°C)"),
                ("Humidity", "Humidity (%)"),
            ),
        ):
            _bins = np.linspace(
                scoped_readings[_column].min(), scoped_readings[_column].max(), 36
            )
            for _state, _name, _color in (
                (0, "Vacant", SLATE),
                (1, "Occupied", SIGNAL),
            ):
                _values = scoped_readings.filter(pl.col("Occupancy") == _state)[
                    _column
                ].to_numpy()
                if len(_values):
                    # Each state is scaled to its own peak, so the shapes compare.
                    _counts, _ = np.histogram(_values, _bins)
                    _shape = _counts / _counts.max()
                    _axis.stairs(_shape, _bins, fill=True, color=_color, alpha=0.2)
                    _axis.stairs(
                        _shape, _bins, color=_color, linewidth=0.8, label=_name
                    )
            _axis.set_title(_label)
            _axis.set_yticks([])
            _axis.spines["left"].set_visible(False)
        _axes[0].legend(loc="upper right")
    sensor_distributions
    return (sensor_distributions,)


@app.cell
def threshold_figure(
    FOG,
    Figure,
    INK,
    SIGNAL,
    SLATE,
    figure_style,
    matplotlib,
    model_summary,
    np,
    pl,
    scored,
    scope_summary,
    threshold_metrics,
):
    _selected = model_summary["threshold"]
    _series = [("Accuracy", "accuracy", "-")]
    # Without occupied readings, recall is undefined and so is precision.
    if scope_summary["occupied"]:
        _series.append(("Precision", "precision", "--"))
        _series.append(("Recall", "recall", "-."))
    # Precision is undefined where the score calls no reading occupied.
    _metrics = threshold_metrics.with_columns(
        pl.when(pl.col("true_positive") + pl.col("false_positive") > 0)
        .then(pl.col("precision"))
        .alias("precision")
    )
    with matplotlib.rc_context(figure_style):
        threshold_figure = Figure(figsize=(3.5, 2.55), layout="constrained")
        _curves, _scores = threshold_figure.subplots(
            2, 1, sharex=True, height_ratios=(1.35, 1)
        )
        for _label, _column, _style in _series:
            _color = INK if _column == "accuracy" else SLATE
            _curves.plot(
                _metrics["threshold"],
                _metrics[_column].to_numpy().astype(float),
                color=_color,
                linestyle=_style,
                linewidth=1,
                label=_label,
            )
            _curves.plot(
                _selected, model_summary[_column], "o", color=_color, markersize=3
            )
        _curves.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        _curves.set_ylim(0, 1.04)
        _curves.legend(loc="lower left", bbox_to_anchor=(0, 1), ncols=3)
        _curves.grid(axis="y", color=FOG, alpha=0.18, linewidth=0.4)
        _bins = np.linspace(0, 1, 41)
        for _state, _color in ((0, SLATE), (1, SIGNAL)):
            _values = scored.filter(pl.col("Occupancy") == _state)["score"].to_numpy()
            if len(_values):
                _counts, _ = np.histogram(_values, _bins)
                _shape = _counts / _counts.max()
                _scores.stairs(_shape, _bins, fill=True, color=_color, alpha=0.2)
                _scores.stairs(_shape, _bins, color=_color, linewidth=0.8)
        _scores.set_yticks([])
        _scores.spines["left"].set_visible(False)
        _scores.set_xlabel("Occupancy score and threshold")
        for _axis in (_curves, _scores):
            _axis.axvline(_selected, color=FOG, linewidth=0.6, linestyle=":")
        _scores.set_xlim(0, 1)
    threshold_figure
    return (threshold_figure,)


@app.cell
def error_episodes(pl, ranked_model_errors):
    # Consecutive misjudged minutes with one outcome form an episode.
    error_episodes = (
        ranked_model_errors.sort("date")
        .with_columns(
            (
                (pl.col("date").diff().dt.total_minutes() > 2)
                | (pl.col("outcome") != pl.col("outcome").shift())
            )
            .fill_null(True)
            .cum_sum()
            .alias("episode")
        )
        .group_by("episode")
        .agg(
            pl.col("date").min().alias("start"),
            pl.col("date").max().alias("end"),
            pl.len().alias("readings"),
            pl.col("outcome").first().cast(pl.String),
            pl.col("Light").mean().alias("light"),
            pl.col("CO2").mean().alias("co2"),
        )
        .sort(["readings", "start"], descending=[True, False])
        .drop("episode")
    )
    error_episodes.head(5)
    return (error_episodes,)


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
