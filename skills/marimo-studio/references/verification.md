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
notebook Python, run the changed cells in the live notebook, using marimo's
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
notebook session open on an edit-mode server. A code-mode URL follows the
Studio tab connected to that session. Request a new URL after the server
restarts, the session changes, or that tab closes.
Authenticate the chosen browser through marimo's normal login. An API access
token authorizes URL lookup. It is never embedded in the returned URL.

Outside code mode, supply the running server URL:

```console
uvx marimo-studio view preview dashboard --target notebook.py \
  --runtime server --server http://127.0.0.1:8000
```

The returned URL keeps the origin and path of the server URL that produced it.
A code-mode URL uses the local address that marimo gives code mode. In a
marimohub session, a code-mode URL uses the hub's public address for the
user's browser. Verify with `show()` when your browser lacks the user's hub
sign-in. When the user's browser reaches the server through a
proxy path prefix, give them the same path beneath their public root, such as
`https://ide.example/s/f3a9/p/8000/dashboard/?runtime=server`. A Prepared
preview follows a Studio tab. Pass `--browser-client` when more than one is
connected.

`show()` activates the user's Studio tab. That tab renders the view in a
sandboxed frame with an opaque origin, so scripts running in the Studio tab
cannot read the frame's document. Inspect it with frame-aware browser
automation, or open the preview URL. Wait for the frame's requested
navigation before checking readiness: its previous document may still be
visible. On an edit-mode server, an open standalone page follows the
development build of each source change and keeps its address, so the user can
watch the view while you edit. On a run-mode server, build the production
profile and reload. For a checkpoint,
request `exact=True` or `--exact` after building the served profile. Opening an
exact URL returns HTTP 409 if its revision differs or current view source is
unbuilt or failed, even while the previous artifact remains available.

Wait with the browser's native selector or predicate tools for
`html[data-marimo-studio-state="ready"]`. A URL from `preview_url()` or
`view preview` renders the view in the top-level document. A view's public
address, such as `/dashboard/`, serves a wrapper page around the view's
sandboxed frame, and the wrapper's top-level `<html>` mirrors the frame's state
and revision, so the same selector works there too. The state leaves `ready`
while the frame replaces its document, rebuilds, or reconnects. Read
`document.documentElement.dataset.marimoStudioRevision` for the committed
presentation revision, which differs from the artifact's `build.revision`.
Studio readiness covers its runtime, mounted projections, and uncaught errors
from view scripts, which set the state to `error` and show their location.
Treat `error` as a failed check even when the top-level page logs no errors,
and read `marimoStudio.diagnostics()` on the top-level page for the view's
records. A failed build keeps the previous build `ready`, so compare the
revision or check `marimoStudio.diagnostics()` for the build's error before
trusting the content.
Assert the application's intended result separately. After changing a control, wait for
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

## Verify at the origin people open

Browsers treat loopback hosts such as `localhost` and `127.0.0.1` as
[secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts),
so a local check can pass while the same page fails for someone opening it
over plain HTTP on another host. `navigator.gpu`, `navigator.clipboard`, and
`crypto.subtle` exist only in a secure context, and a Prepared export verifies
its files with `crypto.subtle`.

Reproduce a remote plain-HTTP origin with
[Playwright](https://playwright.dev/python/), a browser automation library.
Chromium's `--host-resolver-rules` flag points a made-up host name at this
machine:

```console
uvx --from playwright playwright install chromium webkit
```

```python
# check_view.py
import sys

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--host-resolver-rules=MAP insecure.test 127.0.0.1"])
    page = browser.new_page()
    page.on("console", lambda message: print(message.type, message.text))
    page.on("pageerror", lambda error: print("pageerror", error))
    page.goto(sys.argv[1])
    page.wait_for_selector(
        'html[data-marimo-studio-state="ready"], html[data-marimo-studio-state="error"]',
        state="attached",
    )
    print("state:", page.evaluate("document.documentElement.dataset.marimoStudioState"))
    print("diagnostics:", page.evaluate("marimoStudio.diagnostics()"))
    frame = page.query_selector("iframe#marimo-studio-presentation")
    view = frame.content_frame() if frame else page
    print("secure context:", view.evaluate("isSecureContext"))
    browser.close()
```

```console
uv run --no-project --with playwright python check_view.py http://insecure.test:<port>/dashboard/
```

The script prints `secure context: False`, and `True` for
`http://localhost:<port>/dashboard/`. On plain HTTP it also prints browser
notices about the clipboard and COOP headers. The same script runs against a
Prepared export or a `view preview` URL, which render in the top-level document.
A Prepared export on that origin prints `state: error` with
`static-runtime-failed`.

## Run WebKit for iPhone and Safari

A device descriptor such as Playwright's `iPhone 14` sets the viewport and user
agent, and the engine comes from the browser you launch. `requestIdleCallback`
exists in Chromium under that descriptor and is undefined in WebKit, so a view
that calls it passes Chromium emulation and crashes on an iPhone. Replace the
launch and page lines in `check_view.py`, then open a `localhost` URL, because
WebKit has no resolver flag:

```python
browser = p.webkit.launch()
page = browser.new_page(**p.devices["iPhone 14"])
```

Treat a printed `pageerror` as a failed check. A classic inline script that
throws can leave the state at `ready`. Playwright's WebKit is a desktop build
of Safari's engine. Use a real iPhone or the iOS Simulator for touch and
iOS-only behavior.

## Read a framed view's console

On a view's public address, the view, its result hosts, and its console output
live in `iframe#marimo-studio-presentation`. In the Studio tab, find the view's
frame in `page.frames`. `page.on("console", ...)` in `check_view.py` receives
messages from every frame, and `content_frame()` evaluates inside it.

To check the view at the top level, open a `view preview` or `preview_url()`
URL. It applies the same sandbox and puts the console, the full `marimoStudio`
API, and the result hosts on the page. The frame's own `src` needs the wrapper's
session. Opened alone, it stays at `connecting` or fails with
`kernel-disconnected`.
