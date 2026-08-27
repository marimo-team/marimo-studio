# View authoring

Open the notebook-bound workspace in each code-mode execution:

```python
import marimo_studio.agent as studio

workspace = studio.open()
starter = await workspace.starter("marimo-studio/vanilla:default")
view = await workspace.ensure_view("dashboard", starter=starter)
inspection = await view.inspect()
```

Read each editable document immediately before changing it:

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = workspace.view("dashboard")
document = await view.read("index.html")
updated_content = document.content.replace("Current heading", "New heading")
await view.write(
    "index.html",
    updated_content,
    expected_revision=document.revision,
)
```

Keep notebook data, transformations, and controls in Marimo cells. Keep page
structure, styles, copy, and browser behavior in frontend source.

The default starter creates `view.toml` and one root `index.html`. Other
starters may create any source tree and native tool configuration. Starter
identity is not durable project state.

Use these native mounts inside the frontend's projection shell:

```html
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
<strong mo-value="metrics.total"></strong>
```

Prefer literal targets or ordinary constant arrays and records. Inspect
diagnostics after source changes. Build from the view handle:

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = workspace.view("dashboard")
publication = await view.build()
```

A failed build keeps the last valid page. Repair the reported source and build
again. Source conflicts preserve the browser's unsaved buffer and return the
current file revision.

The extension owns source creation, inspection, and candidate build. Studio
owns `view.toml`, `.artifacts/`, validation, publication, sessions, and browser
delivery.
