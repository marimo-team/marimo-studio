# Validation and handoff

Validation is progressive:

```python
import marimo_studio.agent as studio

workspace = studio.open()
static = await workspace.view("dashboard").validate(level="static")
```

```python
import marimo_studio.agent as studio

workspace = studio.open()
runtime = await workspace.view("dashboard").validate(level="runtime")
```

```python
import marimo_studio.agent as studio

workspace = studio.open()
browser = await workspace.view("dashboard").validate(level="browser")
```

Static validation reads saved source and resolves notebook targets. Runtime
validation starts the complete reactive notebook in an isolated process, which
can perform its configured file, network, database, and data access. Studio
then checks the selected view's projected results. Browser validation observes
the active presentation and mounted results.

Before browser validation:

1. Build the changed view.
2. Activate it in the intended browser.
3. Exercise relevant controls and dynamic layouts.
4. Wait for the runtime to report ready.

When several browser clients are connected, select the intended client. Treat
the returned actions as a repair queue. Repeat build, activation, interaction,
and validation until no error action remains.

Inspect the final page at wide and narrow widths. Check the browser console and
failed requests. Report the notebook, view, changed documents, publication
identity, selected browser, and validation level.

Use the same authority and environment the user approved for runtime
validation.
