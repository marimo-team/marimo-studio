# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo==0.24.0",
#     "polars==1.33.1",
# ]
#
# [tool.marimo-studio]
# default = "overview"
# preserve_session = false
# runtime = "server"
# runtimes = ["server", "wasm"]
# show_cell_logs = false
#
# [tool.marimo-studio.cells]
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium", app_title="Rio 2016 Athletes")


@app.cell(hide_code=True)
def introduction(mo):
    mo.md("""
    # Rio 2016 Athletes

    The Rio 2016 roster records 11,538 athletes across 28 sports.
    Participation, body profiles, and athlete medal awards are compared across
    the full field.

    The roster mirrors the [`flother/rio2016`](https://github.com/flother/rio2016)
    dataset derived from the former Rio 2016 site. DataHub publishes it under the
    [ODC-PDDL 1.0](https://opendatacommons.org/licenses/pddl/1-0/) license.
    Height and weight contain missing values, and the source records sex with
    two categories.
    """)
    return


@app.cell
def _():
    import io
    import urllib.request
    from datetime import date

    import marimo as mo
    import polars as pl

    return date, io, mo, pl, urllib


@app.cell(hide_code=True)
def data_context(mo):
    mo.md("""
    ## Athlete records

    Age is calculated on the opening date. Sport, nationality, and sex remain
    categorical fields, while body measurements retain their reported units.
    """)
    return


@app.cell
def load_athletes(date, io, pl, urllib):
    source_url = (
        "https://raw.githubusercontent.com/uwdata/mosaic/"
        "57f509c0f4140e66b0fb0f8b43172ebdd4dbbf6b/data/athletes.csv"
    )
    with urllib.request.urlopen(source_url) as response:
        source = io.BytesIO(response.read())
    athletes = (
        pl.read_csv(source, try_parse_dates=True)
        .with_columns(
            (
                (pl.lit(date(2016, 8, 5)) - pl.col("date_of_birth"))
                .dt.total_days()
                .truediv(365.2425)
                .cast(pl.Float32)
            ).alias("age"),
            (pl.col("gold") + pl.col("silver") + pl.col("bronze"))
            .cast(pl.UInt8)
            .alias("medal_awards"),
        )
        .with_columns(
            pl.col("id").cast(pl.UInt32),
            pl.col("nationality", "sex", "sport").cast(pl.Categorical),
            pl.col("height", "weight").cast(pl.Float32),
            pl.col("gold", "silver", "bronze").cast(pl.UInt8),
        )
    )
    athletes.head(8)
    return (athletes,)


@app.cell(hide_code=True)
def participation_context(mo):
    mo.md("""
    ## Participation

    Select a sport to compare its field size and medal results with the complete
    Games roster.
    """)
    return


@app.cell
def sport_control(athletes, mo):
    sport = mo.ui.dropdown(
        options=["All sports", *athletes["sport"].cast(str).unique().sort().to_list()],
        value="All sports",
        label="Sport",
    )
    sport
    return (sport,)


@app.cell
def participation(athletes, pl, sport):
    selected_athletes = (
        athletes
        if sport.value == "All sports"
        else athletes.filter(pl.col("sport").cast(str) == sport.value)
    )
    athlete_summary = {
        "selection": sport.value,
        "athletes": selected_athletes.height,
        "nationalities": selected_athletes["nationality"].n_unique(),
        "sports": selected_athletes["sport"].n_unique(),
        "medalists": selected_athletes.filter(pl.col("medal_awards") > 0).height,
    }
    selected_roster = (
        selected_athletes.sort(["medal_awards", "name"], descending=[True, False])
        .select(
            "name",
            "nationality",
            "sport",
            "sex",
            "age",
            "height",
            "weight",
            "gold",
            "silver",
            "bronze",
            "medal_awards",
        )
        .with_columns(
            pl.col("age").cast(pl.Float64).round(1),
            pl.col("height").cast(pl.Float64).round(2),
            pl.col("weight").cast(pl.Float64).round(1),
        )
        .head(20)
    )
    top_sports = (
        athletes.group_by("sport")
        .agg(
            pl.len().alias("athletes"),
            (pl.col("medal_awards") > 0).sum().alias("medalists"),
        )
        .sort("athletes", descending=True)
        .head(10)
    )
    selected_roster
    return (athlete_summary,)


@app.cell(hide_code=True)
def profile_context(mo):
    mo.md("""
    ## Sport profiles

    Sport and sex summaries compare participation, body measurements, and medal
    counts while retaining the observed sample sizes.
    """)
    return


@app.cell
def analytical_tables(athletes, pl):
    _summary = athletes.select(
        pl.len().alias("athletes"),
        pl.col("nationality").n_unique().alias("nationalities"),
        pl.col("sport").n_unique().alias("sports"),
        (pl.col("sex").cast(pl.String) == "female").sum().alias("women"),
        (pl.col("sex").cast(pl.String) == "male").sum().alias("men"),
        (pl.col("medal_awards") > 0).sum().alias("medalists"),
        pl.col("medal_awards").sum().alias("medal_awards"),
        (pl.col("medal_awards") > 1).sum().alias("multi_medalists"),
        pl.col("age").cast(pl.Float64).median().round(1).alias("median_age"),
        pl.col("height").cast(pl.Float64).median().round(2).alias("median_height"),
        pl.col("weight").median().round(0).cast(pl.Int64).alias("median_weight"),
        (
            (pl.col("height").fill_null(0) > 0)
            & (pl.col("weight").fill_null(0) > 0)
            & (pl.col("age").fill_null(0) > 0)
        )
        .sum()
        .alias("profile_count"),
    ).row(0, named=True)
    _largest_sport = (
        athletes.group_by("sport")
        .len()
        .sort("len", "sport", descending=[True, False])
        .row(0, named=True)
    )
    games_summary = {
        **_summary,
        "largest_sport": str(_largest_sport["sport"]),
        "largest_count": _largest_sport["len"],
        "medalist_share_percent": round(
            _summary["medalists"] / _summary["athletes"] * 100,
            1,
        ),
        "profile_share_percent": round(
            _summary["profile_count"] / _summary["athletes"] * 100,
            1,
        ),
    }
    sport_profiles = (
        athletes.group_by("sport", "sex")
        .agg(
            pl.len().alias("athletes"),
            pl.col("height").mean().alias("mean_height"),
            pl.col("weight").mean().alias("mean_weight"),
            pl.col("medal_awards").sum().alias("medal_awards"),
        )
        .sort("athletes", "sport", descending=[True, False])
    )
    athlete_facts = athletes.select(
        "id",
        "name",
        "nationality",
        "sex",
        "age",
        "height",
        "weight",
        "sport",
        "gold",
        "silver",
        "bronze",
        "medal_awards",
    )
    sport_profiles.head(12)
    return


@app.cell
def data_quality(athletes, pl):
    quality = {
        "rows": athletes.height,
        "missing_height": athletes.select(pl.col("height").is_null().sum()).item(),
        "missing_weight": athletes.select(pl.col("weight").is_null().sum()).item(),
        "biographies": athletes.filter(pl.col("info").is_not_null()).height,
        "source": "Rio 2016 athlete roster",
    }
    return (quality,)


@app.cell(hide_code=True)
def conclusion(athlete_summary, mo, quality):
    mo.md(f"""
    ## Reading the roster

    **{athlete_summary["selection"]}** contains
    **{athlete_summary["athletes"]:,} athletes** from
    **{athlete_summary["nationalities"]} nationalities**. The source omits
    height for **{quality["missing_height"]:,}** athletes and weight for
    **{quality["missing_weight"]:,}**, so body-profile comparisons retain
    their observed sample sizes.
    """)
    return


if __name__ == "__main__":
    app.run()
