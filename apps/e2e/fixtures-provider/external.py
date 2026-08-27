import marimo

__generated_with = "0.24.0"
app = marimo.App()


@app.cell
def _():
    title = "External provider acceptance"
    return (title,)


if __name__ == "__main__":
    app.run()
