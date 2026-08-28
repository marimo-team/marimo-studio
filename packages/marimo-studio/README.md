# Marimo Studio

Marimo Studio turns one saved marimo notebook into focused web pages for
different audiences. Notebook cells keep the data and computation. Page source
controls the layout, wording, styles, and browser interaction.

Create a page named `dashboard`, then open it beside the notebook:

```console
uvx marimo-studio view create dashboard --target analysis.py
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Choose **Develop** to edit the notebook, page source, and rendered result in one
session. Saving the source rebuilds the page automatically.

The installed Agent Skill gives coding agents the same workflow. An agent can
inspect notebook cells and page source, make revision-safe edits, build the
page, show it in Studio, and validate the rendered result.

Marimo Studio 0.1.0 requires Python 3.10 or newer and Marimo 0.24.0. Read the
[Marimo Studio documentation](https://marimo-team.github.io/marimo-studio/) for
frontend choices, notebook results, deployment, and API reference.

## License

Marimo Studio is licensed under the
[Apache License 2.0](https://github.com/marimo-team/marimo-studio/blob/main/LICENSE).
