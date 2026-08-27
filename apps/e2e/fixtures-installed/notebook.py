import marimo

__generated_with = "0.24.0"
app = marimo.App()


@app.cell
def answer():
    answer = 42
    return (answer,)


if __name__ == "__main__":
    app.run()
