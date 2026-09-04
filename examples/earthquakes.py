# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo==0.24.0",
#     "polars==1.33.1",
#     "tzdata==2026.3",
# ]
#
# [tool.marimo-studio]
# default = "story"
# preserve_session = false
# runtime = "server"
# runtimes = ["server", "wasm", "zero-python"]
# show_cell_logs = false
#
# [tool.marimo-studio.cells]
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium", app_title="Earthquake Watch")


@app.cell(hide_code=True)
def introduction(mo):
    mo.md("""
    # Earthquake Watch

    A fixed USGS weekly feed supports analysis of activity over time,
    logarithmic magnitude, cumulative event frequency, epicenter locations,
    felt reports, source significance, and review status.
    """)
    return


@app.cell
def _():
    import json
    import math
    import urllib.request
    from datetime import UTC, datetime

    import marimo as mo
    import polars as pl

    return UTC, datetime, json, math, mo, pl, urllib


@app.cell(hide_code=True)
def data_context(mo):
    mo.md("""
    ## Weekly event feed

    The committed USGS GeoJSON feed supplies event properties, source links,
    and epicenter coordinates for the weekly record.
    """)
    return


@app.cell
def load_events(UTC, datetime, json, pl, urllib):
    source_url = (
        "https://raw.githubusercontent.com/uwdata/mosaic/"
        "57f509c0f4140e66b0fb0f8b43172ebdd4dbbf6b/data/usgs-feed.geojson"
    )
    with urllib.request.urlopen(source_url) as response:
        payload = json.load(response)

    records = []
    for _feature in payload["features"]:
        _properties = _feature["properties"]
        _coordinates = _feature["geometry"]["coordinates"]
        records.append(
            {
                "id": _feature["id"],
                "magnitude": _properties["mag"],
                "place": _properties["place"],
                "time": datetime.fromtimestamp(_properties["time"] / 1000, tz=UTC),
                "felt": _properties["felt"],
                "status": _properties["status"],
                "tsunami": bool(_properties["tsunami"]),
                "significance": _properties["sig"],
                "url": _properties["url"],
                "longitude": _coordinates[0],
                "latitude": _coordinates[1],
            }
        )
    events = pl.DataFrame(records).with_columns(
        pl.col("magnitude", "longitude", "latitude").cast(pl.Float32),
        pl.col("felt", "significance").cast(pl.Int32),
        pl.col("status").cast(pl.Categorical),
    )
    source_metadata = {**payload["metadata"], "snapshot_url": source_url}
    events.head(8)
    return events, source_metadata


@app.cell(hide_code=True)
def filter_context(mo):
    mo.md("""
    ## Filter the catalog

    Magnitude and review status define a reproducible subset. Weekly totals
    remain based on the complete source snapshot, which makes the effect of
    each selection visible.
    """)
    return


@app.cell
def event_controls(events, mo):
    minimum_magnitude = mo.ui.slider(
        start=2.5,
        stop=float(events["magnitude"].max()),
        step=0.1,
        value=2.5,
        label="Minimum magnitude",
        show_value=True,
    )
    review_status = mo.ui.dropdown(
        options=["All statuses", *events["status"].cast(str).unique().sort().to_list()],
        value="All statuses",
        label="Review status",
    )
    mo.hstack(
        [minimum_magnitude, review_status],
        wrap=True,
        widths="equal",
    )
    return minimum_magnitude, review_status


@app.cell
def filtered_catalog(events, minimum_magnitude, pl, review_status):
    filtered_events = events.filter(pl.col("magnitude") >= minimum_magnitude.value)
    if review_status.value != "All statuses":
        filtered_events = filtered_events.filter(
            pl.col("status").cast(str) == review_status.value
        )
    maximum_magnitude = filtered_events["magnitude"].max() or 0.0
    event_summary = {
        "events": filtered_events.height,
        "maximum_magnitude": float(maximum_magnitude),
        "felt_reports": filtered_events.select(
            pl.col("felt").fill_null(0).sum()
        ).item(),
        "tsunami_flags": filtered_events.select(pl.col("tsunami").sum()).item(),
        "minimum_magnitude": float(minimum_magnitude.value),
        "status": review_status.value,
    }
    filtered_events.head(10)
    return event_summary, filtered_events


@app.cell(hide_code=True)
def magnitude_context(mo):
    mo.md(r"""
    ## Magnitude as a logarithmic measure

    Earthquake magnitude is a logarithmic measure of recorded ground-motion
    amplitude. A difference of one magnitude unit corresponds to about 10 times
    the amplitude and roughly 32 times the released energy.
    """)
    return


@app.cell
def magnitude_reference_control(events, mo):
    comparison_magnitude = mo.ui.slider(
        start=2.5,
        stop=float(events["magnitude"].max()),
        step=0.1,
        value=4.0,
        label="Comparison magnitude",
        show_value=True,
    )
    comparison_magnitude
    return (comparison_magnitude,)


@app.cell
def magnitude_reference_values(events):
    _minimum = 2.5
    _maximum = float(events["magnitude"].max())
    _steps = int(round((_maximum - _minimum) * 10))
    magnitude_comparisons = []
    for _step in range(_steps + 1):
        _reference = round(_minimum + 0.1 * _step, 1)
        _difference = _maximum - _reference
        magnitude_comparisons.append(
            {
                "reference_magnitude": _reference,
                "maximum_magnitude": _maximum,
                "difference": _difference,
                "amplitude_ratio": 10**_difference,
                "energy_ratio": 10 ** (1.5 * _difference),
            }
        )
    return (magnitude_comparisons,)


@app.cell
def magnitude_comparison(comparison_magnitude, magnitude_comparisons, mo):
    _reference = float(comparison_magnitude.value)
    magnitude_scaling = min(
        magnitude_comparisons,
        key=lambda _row: abs(_row["reference_magnitude"] - _reference),
    )
    mo.vstack(
        [
            mo.md(r"""
            \[
            \frac{A_2}{A_1}=10^{\Delta M}
            \qquad
            \frac{E_2}{E_1}\approx10^{1.5\Delta M}
            \]
            """),
            mo.md(f"""
            Comparing **M{magnitude_scaling["maximum_magnitude"]:.1f}** with
            **M{magnitude_scaling["reference_magnitude"]:.1f}** gives
            **{magnitude_scaling["amplitude_ratio"]:,.0f}×** the recorded
            amplitude and approximately
            **{magnitude_scaling["energy_ratio"]:,.0f}×** the released energy.
            """),
        ],
        gap=0.5,
    )
    return (magnitude_scaling,)


@app.cell(hide_code=True)
def activity_context(mo):
    mo.md("""
    ## Activity and reported impact

    Daily counts describe temporal variation. Magnitude, felt reports, and
    source significance describe different aspects of each recorded event.
    """)
    return


@app.cell
def analytical_tables(UTC, datetime, events, pl, source_metadata):
    _period = events.select(
        pl.col("time").min().dt.strftime("%Y-%m-%d").alias("start"),
        pl.col("time").max().dt.strftime("%Y-%m-%d").alias("end"),
    ).row(0, named=True)
    _qualified_events = events.filter(pl.col("magnitude") >= 2.5)
    weekly_summary = {
        "source_events": events.height,
        "qualified_events": _qualified_events.height,
        "maximum_magnitude": float(events["magnitude"].max() or 0.0),
        "felt_reports": events.select(pl.col("felt").fill_null(0).sum()).item(),
        "tsunami_flags": events.select(pl.col("tsunami").sum()).item(),
        "period_start": _period["start"],
        "period_end": _period["end"],
        "generated_at": datetime.fromtimestamp(
            source_metadata["generated"] / 1000,
            tz=UTC,
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_title": source_metadata["title"],
        "source_url": source_metadata["snapshot_url"],
    }
    daily_activity = (
        events.with_columns(pl.col("time").dt.date().alias("day"))
        .group_by("day")
        .agg(
            pl.len().alias("events"),
            pl.col("magnitude").max().alias("maximum_magnitude"),
            pl.col("magnitude").median().alias("median_magnitude"),
            pl.col("felt").fill_null(0).sum().alias("felt_reports"),
        )
        .sort("day")
    )
    strongest_events = (
        events.sort("magnitude", "significance", descending=True)
        .select(
            "id",
            "place",
            "time",
            "magnitude",
            "felt",
            "tsunami",
            "longitude",
            "latitude",
            "url",
        )
        .head(12)
    )
    daily_activity
    return


@app.cell(hide_code=True)
def frequency_context(mo):
    mo.md(r"""
    ## Frequency and magnitude

    The Gutenberg–Richter frequency–magnitude relation describes cumulative
    event counts as a line on a logarithmic count scale. The fit used here is a
    descriptive summary of one global week. Treat it as a description of this
    snapshot rather than an estimate of regional hazard.
    """)
    return


@app.cell
def frequency_magnitude_relation(events, math, mo, pl):
    _minimum = 2.5
    _maximum = float(events["magnitude"].max())
    _steps = int(round((_maximum - _minimum) * 10))
    _thresholds = [round(_minimum + 0.1 * _step, 1) for _step in range(_steps + 1)]
    _rows = []
    for _threshold in _thresholds:
        _count = events.filter(pl.col("magnitude") >= _threshold).height
        if _count > 0:
            _rows.append(
                {
                    "magnitude": _threshold,
                    "events": _count,
                    "log10_events": math.log10(_count),
                }
            )

    _fit_rows = [
        _row for _row in _rows if _row["magnitude"] >= 3.0 and _row["events"] >= 5
    ]
    _mean_magnitude = sum(_row["magnitude"] for _row in _fit_rows) / len(_fit_rows)
    _mean_log_count = sum(_row["log10_events"] for _row in _fit_rows) / len(_fit_rows)
    _variance = sum((_row["magnitude"] - _mean_magnitude) ** 2 for _row in _fit_rows)
    _slope = (
        sum(
            (_row["magnitude"] - _mean_magnitude)
            * (_row["log10_events"] - _mean_log_count)
            for _row in _fit_rows
        )
        / _variance
    )
    _intercept = _mean_log_count - _slope * _mean_magnitude
    _residual = sum(
        (_row["log10_events"] - (_intercept + _slope * _row["magnitude"])) ** 2
        for _row in _fit_rows
    )
    _total = sum((_row["log10_events"] - _mean_log_count) ** 2 for _row in _fit_rows)
    frequency_model = {
        "intercept": _intercept,
        "b_value": -_slope,
        "r_squared": 1 - _residual / _total,
        "fit_minimum": _fit_rows[0]["magnitude"],
        "fit_maximum": _fit_rows[-1]["magnitude"],
        "fit_observations": len(_fit_rows),
    }
    magnitude_exceedance = (
        pl.DataFrame(_rows)
        .with_columns(
            (
                pl.lit(frequency_model["intercept"])
                - pl.lit(frequency_model["b_value"]) * pl.col("magnitude")
            ).alias("fitted_log10_events")
        )
        .with_columns(
            (pl.lit(10.0) ** pl.col("fitted_log10_events")).alias("fitted_events")
        )
    )
    mo.vstack(
        [
            mo.md(r"""
            \[
            \log_{10} N(M\geq m)=a-bm
            \]
            """),
            mo.md(f"""
            **Descriptive weekly fit:**
            M{frequency_model["fit_minimum"]:.1f}–{frequency_model["fit_maximum"]:.1f}
            · b = {frequency_model["b_value"]:.2f}
            · R² = {frequency_model["r_squared"]:.2f}
            """),
        ],
        gap=0.5,
    )
    return frequency_model, magnitude_exceedance


@app.cell
def frequency_threshold_control(frequency_model, mo):
    frequency_threshold = mo.ui.slider(
        start=frequency_model["fit_minimum"],
        stop=frequency_model["fit_maximum"],
        step=0.1,
        value=4.5,
        label="Magnitude threshold",
        show_value=True,
    )
    frequency_threshold
    return (frequency_threshold,)


@app.cell
def frequency_threshold_summary(frequency_threshold, magnitude_exceedance, mo):
    _threshold = round(float(frequency_threshold.value), 1)
    _point = min(
        magnitude_exceedance.to_dicts(),
        key=lambda _row: abs(_row["magnitude"] - _threshold),
    )
    frequency_selection = {
        "magnitude": float(_point["magnitude"]),
        "observed_events": int(_point["events"]),
        "fitted_events": float(_point["fitted_events"]),
    }
    mo.md(f"""
    At **M{frequency_selection["magnitude"]:.1f}+**, the catalog contains
    **{frequency_selection["observed_events"]} events**. The descriptive fit
    gives **{frequency_selection["fitted_events"]:,.0f} events**.
    """)
    return (frequency_selection,)


@app.cell
def catalog_analysis(
    daily_activity,
    events,
    frequency_model,
    magnitude_comparisons,
    magnitude_exceedance,
    mo,
    pl,
    strongest_events,
    weekly_summary,
):
    _event_locations = (
        events.select(
            "id",
            "magnitude",
            "place",
            "time",
            "felt",
            "status",
            "tsunami",
            "significance",
            "url",
            "longitude",
            "latitude",
        )
        .with_columns(
            pl.col("time").dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            pl.lit(False).alias("selected"),
        )
        .sort("magnitude", descending=True)
    )
    _daily_rows = daily_activity.with_columns(pl.col("day").cast(pl.String)).to_dicts()
    _strongest_rows = strongest_events.with_columns(
        pl.col("time").dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    ).to_dicts()
    seismic_analysis = {
        "weekly": weekly_summary,
        "activity": _daily_rows,
        "events": _event_locations.to_dicts(),
        "strongest": _strongest_rows,
        "magnitude": {
            "default_reference": 4.0,
            "comparisons": magnitude_comparisons,
        },
        "frequency": {
            "default_magnitude": 4.5,
            "model": frequency_model,
            "curve": magnitude_exceedance.to_dicts(),
        },
    }
    mo.md(f"""
    ### Catalog analysis

    **{weekly_summary["source_events"]} events**, **{len(_daily_rows)} daily
    observations**, and **{len(magnitude_exceedance)} magnitude thresholds** are
    collected with the complete magnitude and frequency relations in
    `seismic_analysis`.
    """)
    return (seismic_analysis,)


@app.cell(hide_code=True)
def weekly_conclusion(events, mo, source_metadata):
    mo.md(f"""
    ## Weekly context

    The weekly feed contains **{source_metadata["count"]} USGS events** with
    a maximum magnitude of **{events["magnitude"].max():.1f}**. Every record
    retains its time, epicenter coordinates, review status, and source URL for
    subsequent analysis.
    """)
    return


@app.cell(hide_code=True)
def filtered_subset_summary(event_summary, mo):
    mo.md(f"""
    ## Filtered subset

    The **M{event_summary["minimum_magnitude"]:.1f}+ ·
    {event_summary["status"].lower()}** subset contains
    **{event_summary["events"]} events**. Its largest event is
    **M{event_summary["maximum_magnitude"]:.1f}**, with
    **{event_summary["felt_reports"]:,} felt reports** and
    **{event_summary["tsunami_flags"]} tsunami flags** in the selected set.
    """)
    return


if __name__ == "__main__":
    app.run()
