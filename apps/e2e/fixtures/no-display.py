# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio"]
#
# [tool.marimo-studio]
# default = "empty-html"
# runtime = "server"
# runtimes = ["server", "wasm"]
#
# [tool.marimo-studio.cells]
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(app_title="No display results")


@app.cell
def producer():
    value = 1
    return (value,)


@app.cell
def consumer(value):
    hidden = value * 2
    hidden;
    return (hidden,)


@app.cell(disabled=True)
def disabled_output():
    "Disabled output"
    return


if __name__ == "__main__":
    app.run()
