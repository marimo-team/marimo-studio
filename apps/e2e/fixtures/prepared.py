# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "anywidget==0.9.21",
#   "marimo-studio",
# ]
#
# [tool.marimo-studio]
# default = "prepared"
# runtime = "zero-python"
# runtimes = ["server", "wasm", "zero-python"]
# preserve_session = false
# ///

import marimo

__generated_with = "0.24.0"
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
def filters_control(mo, scale):
    region = mo.ui.dropdown(
        options={"Europe": "emea", "Asia Pacific": "apac"},
        value="Europe",
        label="Region",
    )
    fields = {"region": region}
    if scale.value == 3:
        fields["detail"] = mo.ui.text(value="ready", label="Detail")
    filters = mo.ui.dictionary(fields, label="Filters").form(
        submit_button_label="Apply filters"
    )
    filters
    return (filters,)


@app.cell
def filter_state(filters, mo):
    selected_region = (
        "unsubmitted" if filters.value is None else filters.value["region"]
    )
    filter_summary = mo.md(f"Selected region: **{selected_region}**")
    filter_summary
    return (filter_summary, selected_region)


@app.cell
def metric(scale):
    metric = scale.value * 21
    print(f"prepared metric: {metric}")
    metric
    return (metric,)


@app.cell
def summary(metric, mo):
    rich_summary = mo.Html(f"<article><h3>Current total: {metric}</h3></article>")
    rich_summary
    return (rich_summary,)


@app.cell
def counter_widget():
    import anywidget
    import traitlets

    class CounterWidget(anywidget.AnyWidget):
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

    counter = CounterWidget()
    counter
    return (counter,)


if __name__ == "__main__":
    app.run()
