# Verify the displayed result

Examples assume `view` belongs to the intended notebook and named view in the
current call.

After editing view source, build and inspect freshness:

```python
build = await view.build()
inspection = await view.inspect()
print(build.revision, inspection.freshness)
```

`inspect()` reports development build freshness. A failed build retains the
previous successful artifact, so a working page can still show earlier source.
Repair the inspection diagnostic before continuing. For a run-mode server,
build with `profile="production"` and request an exact URL for the served
profile. `inspect().freshness` continues to describe development even after a
production build. Verify production through the exact URL and its displayed
presentation revision, then assert the application's behavior.

Building view source does not execute modified notebook cells. After editing
notebook Python, run the changed cells in the live notebook, using Marimo's
**Run all** action when appropriate. Static checks and isolated runtime
validation do not update the live notebook session.

Obtain its URL in code mode:

```python
import marimo_studio

view = marimo_studio.agent.current_workspace().view("dashboard")
print(await view.preview_url(runtime="server"))
```

Choose the intended runtime explicitly. Finish the execution, then open the URL
with the chosen browser tool. Run kernel-dependent browser interactions and
waits through an external tool or interpreter. Waiting synchronously inside
code mode can block the notebook work being awaited. The URL renders a separate top-level
presentation with the server's authentication and document sandbox. Keep the
notebook session open on an edit-mode server.
Authenticate the chosen browser through Marimo's normal login. An API access
token authorizes URL lookup. It is never embedded in the returned URL.

Outside code mode, supply the running server URL:

```console
marimo-studio view preview dashboard --target notebook.py \
  --runtime server --server http://127.0.0.1:8000
```

`show()` activates the user's Studio tab. To inspect that frame, wait for its
requested navigation before checking readiness: its previous document may
still be visible. Once the standalone page is open,
iterate by building and reloading its stable URL. For a checkpoint,
request `exact=True` or `--exact` after building the served profile. Opening an
exact URL returns HTTP 409 if its revision differs or current view source is
unbuilt or failed, even while the previous artifact remains available.

Wait with the browser's native selector or predicate tools for
`html[data-marimo-studio-state="ready"]`. Read
`document.documentElement.dataset.marimoStudioRevision` for the committed
presentation revision, which differs from the artifact's `build.revision`.
Studio readiness covers its runtime and mounted projections. Assert the
application's intended result separately. After changing a control, wait for
the dependent metric, text, and custom chart to update. The selected control
value alone does not prove reactive completion.

If readiness stalls, read the visible status or error and inspect console and
network failures before retrying or restarting. Follow a request to run changed
notebook cells by executing them in the live notebook. Use normal framework
lifecycles and accessible loading and error states for application rendering.
`aria-busy="false"` means work settled, including failed work.

After navigation or reactive updates, wait for the application's chart, slide,
and layout transitions to settle before capturing wide and narrow screenshots.
Inspect the images with an image-capable tool and use findings to guide the
next edit. At narrow widths, check readable text and usable controls as well as
overflow. A scaled desktop layout can fit while becoming unusable. Saving an
image path alone does not check layout. Repeat edit, build, freshness check,
reload, and assertions until the intended result passes. Report visual checks
as blocked if the environment cannot capture or inspect images.

Use `view.validate(level="static")` for saved source and projection declarations,
or `level="runtime"` to execute the saved notebook in an isolated process.
