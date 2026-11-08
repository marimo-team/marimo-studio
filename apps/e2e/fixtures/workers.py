# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "marimo-studio",
#     "marimo-studio-e2e-provider==1.0.0"
# ]
#
# [tool.uv.sources]
# marimo-studio-e2e-provider = { path = "../fixtures-provider/provider" }
#
# [tool.marimo-studio]
# default = "workers"
# provider_dependencies = ["marimo-studio-e2e-provider==1.0.0"]
# runtime = "server"
# runtimes = ["server", "wasm"]
#
# [tool.marimo-studio.cells]
# ///

import marimo

app = marimo.App()


@app.cell
def _():
    metric = 42
    return (metric,)


if __name__ == "__main__":
    app.run()
