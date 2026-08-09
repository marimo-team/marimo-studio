# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "anywidget==0.9.21",
#   "marimo>=0.23.16",
#   "marimo-studio",
# ]
#
# [tool.marimo-studio]
# default = "dashboard"
# preserve_session = false
# ///

import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium")


@app.cell
def imports():
    import marimo as mo

    return (mo,)


@app.cell
def controls(mo):
    scale = mo.ui.slider(
        start=1,
        stop=3,
        value=2,
        show_value=True,
        label="Scale",
    )
    scale
    return (scale,)


@app.cell
def metric(scale):
    metric = scale.value * 21
    responsive_value = "responsive" * 80
    metric
    return metric, responsive_value


@app.cell
def counter_widget():
    import anywidget
    import traitlets

    class CounterWidget(anywidget.AnyWidget):
        _esm = """
        export function render({ model, el }) {
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
        }
        """
        value = traitlets.Int(7).tag(sync=True)

    counter = CounterWidget()
    counter
    return (counter,)


@app.cell
def summary(metric, mo):
    mo.md(f"### Current total: {metric}")
    return


if __name__ == "__main__":
    app.run()
