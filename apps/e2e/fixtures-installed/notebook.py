import marimo

__generated_with = "0.24.0"
app = marimo.App()


@app.cell
def controls():
    import marimo as mo

    scale = mo.ui.slider(1, 3, value=2, label="Scale")
    scale
    return (scale,)


@app.cell
def answer(scale):
    answer = scale.value * 21
    return (answer,)


if __name__ == "__main__":
    app.run()
