# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "marimo-studio",
# ]
#
# [tool.marimo-studio]
# default = "dashboard"
# preserve_session = false
#
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium")


@app.cell
def imports():
    from datetime import date

    import marimo as mo

    return date, mo


@app.cell
def controls(mo):
    scenario = mo.ui.dropdown(
        options=["Base", "Growth", "Stretch"],
        value="Growth",
        label="Scenario",
    )
    quarter = mo.ui.slider(
        start=1,
        stop=4,
        step=1,
        value=4,
        show_value=True,
        label="Through quarter",
    )
    mo.hstack([scenario, quarter], justify="start", wrap=True, gap=2)
    return quarter, scenario


@app.cell
def forecast(date, quarter, scenario):
    multipliers = {"Base": 1.0, "Growth": 1.15, "Stretch": 1.3}
    baseline = [240, 270, 310, 350]
    selected = baseline[: int(quarter.value)]
    multiplier = multipliers[scenario.value]
    projected = [round(amount * multiplier) for amount in selected]

    rows = [
        {
            "Quarter": f"Q{index}",
            "Baseline": f"${base_amount:,}k",
            "Projection": f"${projected_amount:,}k",
        }
        for index, (base_amount, projected_amount) in enumerate(
            zip(selected, projected, strict=True),
            start=1,
        )
    ]
    total = sum(projected)
    change = (multiplier - 1) * 100
    today = date.today()
    report = {
        "scenario": scenario.value,
        "through": f"Q{quarter.value}",
        "total": f"${total:,}k",
        "change": f"{change:+.0f}%",
        "updated_at": f"{today.day} {today:%B %Y}",
    }
    return report, rows


@app.cell
def summary(mo, report):
    summary = mo.md(f"""
    ### {report["scenario"]} outlook

    Projected revenue through **{report["through"]}** is
    **{report["total"]}**, a **{report["change"]}** change from baseline.
    """)
    summary
    return (summary,)


@app.cell
def revenue_table(mo, rows):
    revenue_table = mo.ui.table(
        rows,
        pagination=False,
        selection=None,
        show_column_summaries=False,
        show_data_types=False,
        show_download=False,
        show_search=False,
        text_justify_columns={
            "Quarter": "left",
            "Baseline": "right",
            "Projection": "right",
        },
    )
    revenue_table
    return (revenue_table,)


@app.cell(hide_code=True)
def _():
    # marimo-lens: agent-managed Lens cell
    import importlib.util as _importlib_util

    import marimo as _mo

    if _importlib_util.find_spec("marimo_lens") is None:
        lens = _mo.md("Install `marimo-lens` to annotate this Studio view.")
    else:
        from marimo_lens import Lens as _Lens
        from marimo_studio import LENS_TARGET_SELECTOR as _LENS_TARGET_SELECTOR

        lens = _Lens(
            dom_selector=(
                f"{_LENS_TARGET_SELECTOR}, "
                "#app-shell :is(header, section, article)"
            ),
        )
    _mo.output.append(lens)
    return (lens,)


if __name__ == "__main__":
    app.run()
