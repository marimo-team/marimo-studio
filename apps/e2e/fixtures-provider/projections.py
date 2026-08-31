# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo-studio[deno]"]
#
# [tool.marimo-studio]
# default = "overview"
# preserve_session = false
# show_cell_logs = false
#
# [tool.marimo-studio.cells]
#
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App()


@app.cell
def imports():
    import marimo as mo

    return (mo,)


@app.cell
def controls(mo):
    scale = mo.ui.slider(1, 3, value=2, label="Scale")
    scale
    return (scale,)


@app.cell
def metric(scale):
    metric = scale.value * 21
    metric
    return (metric,)


@app.cell
def records(mo):
    records = mo.ui.table(
        [
            {
                "name": "Alpha",
                "value": 21,
                "category": "Primary",
                "status": "Ready",
                "description": "First projected record",
            },
            {
                "name": "Beta",
                "value": 42,
                "category": "Secondary",
                "status": "Ready",
                "description": "Second projected record",
            },
            {
                "name": "Gamma",
                "value": 63,
                "category": "Tertiary",
                "status": "Ready",
                "description": "Third projected record",
            },
        ]
    )
    records
    return (records,)


@app.cell
def first_result(mo):
    first = mo.md("### First projected result")
    first
    return (first,)


@app.cell
def second_result(mo):
    second = mo.md("### Second projected result")
    second
    return (second,)


if __name__ == "__main__":
    app.run()
