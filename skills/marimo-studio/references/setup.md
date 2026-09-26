# Connect and select the environment

Use the notebook's Python environment for Studio operations. If the briefing
came from a disposable terminal environment, connect through Marimo's
**Code Mode** sidebar or `marimo pair execute`, then read the installed
briefing in the notebook kernel:

```python
import marimo_studio

help(marimo_studio.agent)
```

The help text contains the installed core briefing with Python API help.
Reading guidance is passive. It does not bind a workspace or activate a view.
Reuse instructions while the environment and installation remain the same. A
terminal can obtain a briefing before connecting:

```console
uvx --with marimo-studio agent-plugins read marimo-studio
```

`marimo pair notebook list` reports running servers with their notebooks and
sessions. Target the notebook the user opened in Studio with
`marimo pair execute --url <URL> --file <PATH>`, passing the absolute `path`
from that list. A relative file resolves against the agent's working
directory. A notebook has a session once a browser opens it, and `view.show()`
needs that open Studio tab.

## Work from a saved notebook

Outside code mode, bind the saved notebook explicitly:

```python
import asyncio

from marimo_studio.authoring import open_workspace

workspace = open_workspace("notebook.py")
print(asyncio.run(workspace.status()))
```

Saved-workspace APIs support source inspection, view authoring, and builds.
The CLI targets the same notebook with `--target notebook.py`. Preview URL
lookup additionally requires the running Studio server:

```console
marimo-studio view preview dashboard --target notebook.py \
  --runtime server --server http://127.0.0.1:8000
```

Inside code mode, use `marimo_studio.agent.current_workspace()` to bind the
current notebook and Studio browser client. A missing host connection requires
an open Studio editor connected to that notebook. Reading or building saved
source does not establish a browser connection.

## Check missing capabilities

Inspect installed starter availability with `await workspace.starters()`.
Use dependency diagnostics before validation or export:

```console
marimo-studio doctor --dependencies --target notebook.py --json
```

Read its interpreter path, declaration drift, provider requirements, and import
availability. This inspects dependencies without executing notebook cells.
Preserve project-managed execution with `uv run --project <root>` and
`--no-sandbox`. Use `--sandbox` when the notebook's PEP 723 dependencies own
execution. Pass the exact `status.launch_requirements` through the environment
tool when launching a notebook.

`metadata-drift` compares notebook declarations with the owning project's direct
`project.dependencies`. It can occur when imports are available through a
workspace or dependency group. The command exits with status 1 for any reported
issue. Inspect `issues`, `declarations`, and `imports` separately, confirm which
environment owns execution, and repair missing requirements in that environment.
An intentional declaration difference alone does not establish a missing import
or require changing unrelated project metadata.

Framework starters need the Deno supplied by `marimo-studio[deno]` in the
notebook's environment. Run dependency commands from the view root using that
version, following the project's `AGENTS.md`. For a separate tool environment,
use `uvx --from 'deno==<installed-deno-version>' deno`. Pinning Studio alone
does not pin Deno. Preserve the project's dependency age policy and commit
changed dependency manifests with their lockfiles.
