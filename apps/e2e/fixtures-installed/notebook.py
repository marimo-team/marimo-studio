# /// script
# requires-python = ">=3.10"
# dependencies = ["anywidget==0.9.21"]
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App()


@app.cell
def controls():
    import marimo as mo

    scale = mo.ui.slider(1, 3, value=2, label="Scale")
    scale
    return mo, scale


@app.cell
def answer(scale):
    answer = scale.value * 21
    return (answer,)


@app.cell
def summary(answer, mo):
    summary = mo.md(f"### Prepared total: {answer}")
    summary
    return (summary,)


@app.cell
def widget():
    import anywidget
    import traitlets

    class Counter(anywidget.AnyWidget):
        _esm = """
        export default {
          render({ model, el }) {
            const button = document.createElement("button");
            const update = () => {
              button.textContent = `Widget count: ${model.get("value")}`;
            };
            button.addEventListener("click", () => {
              model.set("value", model.get("value") + 1);
              model.save_changes();
            });
            model.on("change:value", update);
            update();
            el.append(button);
            return () => model.off("change:value", update);
          },
        };
        """
        value = traitlets.Int(7).tag(sync=True)

    counter = Counter()
    counter
    return (counter,)


if __name__ == "__main__":
    app.run()
