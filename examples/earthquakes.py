# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo==0.24.0",
#     "polars==1.33.1",
# ]
#
# [tool.marimo-studio]
# default = "story"
# preserve_session = false
# runtime = "server"
# runtimes = ["server", "wasm"]
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

    A fixed USGS weekly feed records magnitude 2.5 and greater earthquakes
    worldwide. Daily activity, event locations, felt reports, review status,
    and tsunami flags define the weekly picture.
    """)
    return


@app.cell
def _():
    import json
    import urllib.request
    from datetime import UTC, datetime

    import marimo as mo
    import polars as pl

    return UTC, datetime, json, mo, pl, urllib


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
    source_metadata = payload["metadata"]
    events.head(8)
    return events, source_metadata


@app.cell(hide_code=True)
def filter_context(mo):
    mo.md("""
    ## Situation filter

    Magnitude and review status define the current operating cut. Weekly totals
    remain based on the complete feed.
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
def situation(events, minimum_magnitude, pl, review_status):
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
def activity_context(mo):
    mo.md("""
    ## Activity and consequence

    Daily counts describe tempo. Magnitude, felt reports, and significance
    identify events that merit closer review.
    """)
    return


@app.cell
def analytical_tables(events, pl):
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
    }
    daily_activity = (
        events.with_columns(pl.col("time").dt.date().alias("day"))
        .group_by("day")
        .agg(
            pl.len().alias("events"),
            pl.col("magnitude").max().alias("maximum_magnitude"),
        )
        .sort("day")
    )
    strongest_events = (
        events.sort("magnitude", "significance", descending=True)
        .select("id", "place", "time", "magnitude", "felt", "tsunami", "url")
        .head(12)
    )
    daily_activity
    return daily_activity, strongest_events, weekly_summary


@app.cell(hide_code=True)
def weekly_conclusion(events, mo, source_metadata):
    mo.md(
        f"""
        ## Weekly context

        The weekly feed contains **{source_metadata["count"]} USGS events** with
        a maximum magnitude of **{events["magnitude"].max():.1f}**. Each event
        retains its USGS record for follow-up.
        """
    )
    return


@app.cell(hide_code=True)
def conclusion(event_summary, mo):
    mo.md(
        f"""
        ## Current watch position

        The **M{event_summary["minimum_magnitude"]:.1f}+ ·
        {event_summary["status"].lower()}** review cut retains
        **{event_summary["events"]} events**. Its largest event is
        **M{event_summary["maximum_magnitude"]:.1f}**, with
        **{event_summary["felt_reports"]:,} felt reports** and
        **{event_summary["tsunami_flags"]} tsunami flags** in the selected set.
        """
    )
    return


if __name__ == "__main__":
    app.run()
