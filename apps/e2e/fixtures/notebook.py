# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "anywidget==0.9.21",
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

    class MixedControlCache:
        def __init__(self):
            self.control = None

    mixed_control_cache = MixedControlCache()
    return mixed_control_cache, mo


@app.cell
def controls(mo):
    fail_outputs = mo.ui.switch(
        value=False,
        label="Fail projected outputs",
    )
    scale = mo.ui.slider(
        start=1,
        stop=3,
        value=2,
        show_value=True,
        label="Scale",
    )
    mo.vstack([scale, fail_outputs])
    return fail_outputs, scale


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
def rich_outputs(fail_outputs, metric, mixed_control_cache, mo):
    if fail_outputs.value:
        raise RuntimeError("Projected output fixture failure")

    class SharedProjectedControl:
        def __init__(self):
            self.control = None

        def _mime_(self):
            if self.control is None:
                self.control = mo.ui.slider(
                    start=1,
                    stop=3,
                    value=1,
                    show_value=True,
                    label="Shared projected control",
                )
            return self.control._mime_()

    class FreshProjectedControl:
        def __init__(self, value):
            self.value = value
            self.control = None

        def _mime_(self):
            if self.control is None:
                self.control = mo.ui.slider(
                    start=1,
                    stop=3,
                    value=self.value,
                    show_value=True,
                    label="Fresh projected control",
                )
            return self.control._mime_()

    class MixedProjectedControls:
        def __init__(self, value, cache):
            self.value = value
            self.cache = cache
            self.fresh = None

        def _mime_(self):
            if self.fresh is None:
                self.fresh = mo.ui.slider(
                    start=1,
                    stop=3,
                    value=self.value,
                    show_value=True,
                    label="Mixed fresh control",
                )
            if self.cache.control is None:
                self.cache.control = mo.ui.slider(
                    start=1,
                    stop=3,
                    value=1,
                    show_value=True,
                    label="Mixed cached control",
                )
            return mo.hstack([self.fresh, self.cache.control])._mime_()

    alternate_summary = mo.md(f"### Alternate total: {metric}")
    fresh_control = FreshProjectedControl(metric // 21)
    long_output = {
        "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx": mo.md(
            "Long selector ready"
        )
    }
    projected_control = SharedProjectedControl()
    projected_control_alias = projected_control
    projected_control_peer = projected_control
    mixed_controls = MixedProjectedControls(metric // 21, mixed_control_cache)
    rich_summary = mo.md(f"### Current total: {metric}")
    rich_table = mo.ui.table(
        [{"Measure": "Current total", "Value": metric}],
        selection=None,
        pagination=False,
    )
    return (
        alternate_summary,
        fresh_control,
        long_output,
        mixed_controls,
        projected_control,
        projected_control_alias,
        projected_control_peer,
        rich_summary,
        rich_table,
    )


if __name__ == "__main__":
    app.run()
