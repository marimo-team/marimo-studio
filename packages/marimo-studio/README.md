# Marimo Studio

Marimo Studio keeps one reproducible marimo notebook as the analytical model
and lets you build a purpose-built web view for each job. The notebook keeps
data access, transformations, controls, and reusable results together as one
reactive Python program. Each named view owns its frontend source, layout, and
interaction while drawing from notebook cells, outputs, and values.

All Python computation runs in the notebook. View source references notebook
results by name and controls their layout and browser interaction.

Create a view named `dashboard`, then open it beside the notebook:

```console
uvx marimo-studio view create dashboard --target analysis.py
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Choose **Develop** to edit the notebook, view source, and rendered result in one
session. Saving the source rebuilds the view automatically.

The installed Agent Skill gives coding agents the same workflow. People and
agents inspect the same notebook and view source, make revision-safe edits,
build, preview, and validate the rendered result.

Marimo Studio 0.1.0 requires Python 3.10 or newer and Marimo 0.24.0. Read the
[Marimo Studio documentation](https://marimo-team.github.io/marimo-studio/) for
frontend choices, notebook results, deployment, and API reference. Read [Why
Studio?](https://marimo-team.github.io/marimo-studio/why-studio) for the product
model.

## License

Marimo Studio is licensed under the
[Apache License 2.0](https://github.com/marimo-team/marimo-studio/blob/main/LICENSE).
