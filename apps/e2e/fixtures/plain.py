import marimo

app = marimo.App()


@app.cell
def _():
    "Native Marimo notebook"
    return


if __name__ == "__main__":
    app.run()
