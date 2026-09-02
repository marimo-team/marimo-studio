# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "marimo-studio",
#     "marimo-studio-e2e-provider==1.0.0"
# ]
#
# [tool.uv.sources]
# marimo-studio-e2e-provider = { path = "../../../fixtures-provider/provider" }
#
# [tool.marimo-studio]
# default = "dashboard"
# provider_dependencies = ["marimo-studio-e2e-provider==1.0.0"]
#
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App()


@app.cell
def _():
    title = "External provider acceptance"
    return (title,)


if __name__ == "__main__":
    app.run()
