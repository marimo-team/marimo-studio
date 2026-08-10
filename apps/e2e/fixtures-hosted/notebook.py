# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "marimo>=0.23.16",
#   "marimo-studio",
# ]
#
# [tool.marimo-studio]
# default = "dashboard"
# preserve_session = false
# ///

import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium")


@app.cell
def imports():
    import marimo as mo

    return (mo,)


@app.cell
def controls(mo):
    scale = mo.ui.slider(
        start=1,
        stop=3,
        value=2,
        show_value=True,
        label="Hosted scale",
    )
    scale
    return (scale,)


@app.cell
def metric(scale):
    metric = scale.value * 21
    metric
    return (metric,)


@app.cell
def summary(metric, mo):
    mo.md(f"""
    ### Hosted total: {metric}
    """)
    return


if __name__ == "__main__":
    app.run()
