# Marimo Studio

Marimo Studio builds custom reports, apps, and presentations from one
[marimo](https://marimo.io/) notebook. Keep the analysis in Python, then shape
each view with HTML, [React](https://react.dev/),
[Svelte](https://svelte.dev/), or the browser libraries your work needs.

Marimo Studio 0.1 is experimental. Pin Studio and third-party view providers in
saved projects.

## Create your first view

Open a notebook in an environment that contains Studio:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

`uvx` is [uv](https://docs.astral.sh/uv/)'s temporary command runner. It creates
an isolated Python environment for this invocation.

Add a displayable cell and save the notebook. Studio opens the first-view
screen. Create a view named `dashboard`, then choose **Develop** to edit the
notebook, view source, and rendered Preview together.

For terminal-first setup with an existing saved notebook, run:

```console
uvx marimo-studio view create dashboard --target analysis.py
```

Saving Source builds a new immutable artifact. A failed build reports the source
problem and keeps the current artifact available.

## Choose a runtime

- The **Python runtime** uses a server-side marimo session and can access local
  files, databases, credentials, and native packages.
- The **Browser runtime** runs the saved notebook in a
  [Pyodide](https://pyodide.org/) worker. Pyodide is a Python distribution
  compiled for the browser. The browser receives notebook source and must be
  able to fetch its dependencies and data.
- The **Prepared runtime** computes finite input states during static export
  and serves verified results to the view. Visitors receive the view and its
  prepared outputs with no Python runtime.

## Continue

- [Start here](https://marimo-team.github.io/marimo-studio/guide/)
- [Examples](https://marimo-team.github.io/marimo-studio/examples/)
- [Run or export a view](https://marimo-team.github.io/marimo-studio/guide/run-and-share)
- [Reference](https://marimo-team.github.io/marimo-studio/reference/)
- [Compatibility and support](https://marimo-team.github.io/marimo-studio/reference/compatibility)
- [Troubleshooting](https://marimo-team.github.io/marimo-studio/guide/troubleshooting)
- [Security](https://github.com/marimo-team/marimo-studio/blob/main/SECURITY.md)

Use [GitHub Issues](https://github.com/marimo-team/marimo-studio/issues) for
public bug reports and support requests.

## License

Marimo Studio is licensed under the
[Apache License 2.0](https://github.com/marimo-team/marimo-studio/blob/main/LICENSE).
