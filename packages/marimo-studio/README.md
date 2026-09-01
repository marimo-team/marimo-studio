# Marimo Studio

**One notebook. A studio for every view.**

Marimo Studio keeps one reproducible marimo notebook as the analytical model
and lets you build a purpose-built web view for each job. The notebook keeps
data access, transformations, controls, and reusable results together as one
reactive Python program. Each named view owns its frontend source, layout, and
interaction while drawing from notebook cells, outputs, and values.

Marimo Studio 0.1.0 is the first public release. Pin Studio and third-party view
providers in saved projects. Public CLI, Python, provider, and saved
configuration contracts may change between minor releases before 1.0.

All Python computation runs in the notebook. View source references notebook
results by name and controls their layout and browser interaction.

Create a view named `dashboard`, then open it beside the notebook:

```console
uvx --from marimo-studio==0.1.0 marimo-studio view create dashboard --target analysis.py
uvx --with marimo-studio==0.1.0 marimo edit analysis.py --sandbox
```

Choose **Develop** to edit the notebook, view source, and rendered result in one
session. The create command writes the `dashboard` view project and makes it the
default route. Saving its source rebuilds the view automatically. A failed build
keeps the last successful result available.

The installed Agent Skill gives coding agents the same workflow. People and
agents inspect the same notebook and view source, make revision-safe edits,
build, preview, and validate the rendered result.

See the [Rio athletes
example](https://marimo-team.github.io/marimo-studio/examples/athletes) for one
notebook rendered as a report, linked explorer, and interactive briefing.

Marimo Studio 0.1.0 supports Python 3.10 through 3.14 and Marimo 0.24.0. Read
[Why Studio?](https://marimo-team.github.io/marimo-studio/why-studio) for the
product model and the [Marimo Studio
documentation](https://marimo-team.github.io/marimo-studio/) for frontend
choices, notebook results, deployment, and API reference. See [Compatibility
and support](https://marimo-team.github.io/marimo-studio/reference/compatibility)
and [Troubleshooting](https://marimo-team.github.io/marimo-studio/guide/troubleshooting)
before maintaining or deploying a view.

Use [GitHub Issues](https://github.com/marimo-team/marimo-studio/issues) for
public bug reports and support requests. Report suspected vulnerabilities
through the private path in the [security
policy](https://github.com/marimo-team/marimo-studio/blob/main/SECURITY.md).

## License

Marimo Studio is licensed under the
[Apache License 2.0](https://github.com/marimo-team/marimo-studio/blob/main/LICENSE).
