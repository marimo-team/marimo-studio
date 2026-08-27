# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio"]
#
# [tool.marimo-studio]
# default = "dashboard"
#
# [tool.marimo-studio.cells]
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App()


@app.cell
def summary():
    value = "migrated"
    value  # noqa: B018
    return (value,)


if __name__ == "__main__":
    app.run()
