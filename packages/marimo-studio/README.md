# Marimo Studio

Marimo Studio lets one reproducible marimo notebook support several
purpose-built web views. Notebook cells keep the data, Python computation,
controls, and reusable results. Each view owns its frontend source, layout,
wording, styles, and browser interaction for a particular job.

All Python computation runs in the notebook. View source references notebook
results by name and controls their layout and browser interaction.

Create a view named `dashboard`, then open it beside the notebook:

```console
uvx marimo-studio view create dashboard --target analysis.py
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Choose **Develop** to edit the notebook, view source, and rendered result in one
session. Saving the source rebuilds the view automatically.

The installed Agent Skill gives coding agents the same workflow. An agent can
inspect notebook cells and view source, make revision-safe edits, build the
view, show it in Studio, and validate the rendered result.

Marimo Studio 0.1.0 requires Python 3.10 or newer and Marimo 0.24.0. Read the
[Marimo Studio documentation](https://marimo-team.github.io/marimo-studio/) for
frontend choices, notebook results, deployment, and API reference. Read [Why
Studio?](https://marimo-team.github.io/marimo-studio/why-studio) for the product
model.

## License

Marimo Studio is licensed under the
[Apache License 2.0](https://github.com/marimo-team/marimo-studio/blob/main/LICENSE).
