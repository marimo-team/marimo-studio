import marimo

app = marimo.App()


@app.cell
def _():
    summary = {"papers": 3877}
    "Native Marimo notebook"
    return (summary,)


if __name__ == "__main__":
    app.run()
