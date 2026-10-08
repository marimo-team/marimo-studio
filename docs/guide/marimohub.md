---
title: Use Studio in marimohub
description: Add Studio to a marimohub notebook, create a view in the hub editor, serve it as the notebook's app, and author views with coding agents.
---

# Use Studio in marimohub

[marimohub](https://marimohub.docs.marimo.io/) is a self-hosted platform that
stores marimo notebooks and runs each session in a sandbox. When a notebook
declares `marimo-studio`, the hub installs Studio into the sandbox, the
notebook page opens the Studio authoring workspace, and **Run as app** serves
the view the editor shows.

![A marimohub notebook page with the notebook beside a live dashboard Preview](/screenshots/marimohub/studio-workspace.png)

This guide covers marimohub 0.4.16 and later.

## Persist view projects

marimohub copies `notebook.py` and `pyproject.toml` into each sandbox and saves
them when the session ends. Studio writes view projects to the same sandbox
workspace, and the hub saves those files when the deployment sets:

```console
MARIMOHUB_PERSIST_WORKSPACE=workspace
```

Workspace persistence saves hidden files such as `.env` too, and any project
member with read access can download them. Keep credentials in the hub's
[integration secrets](https://marimohub.docs.marimo.io/integration-secrets).

With the default `source` value, view files are lost when the session ends, and
**Add view** says so before it creates a view. Git-synced notebooks, temporary
editors, and previews save nothing from the session, and **Add view** warns
about those sessions too. For a Git-synced notebook, commit `notebook.py` and
the view folder to the repository before you stop the session, as the hub's
[marimo-studio steps](https://marimohub.docs.marimo.io/apps#use-marimo-studio)
describe. See the hub's
[configuration reference](https://marimohub.docs.marimo.io/configuration) for
the setting.

Studio marks each view's build cache and unfinished builds with a
[`CACHEDIR.TAG`](https://bford.info/cachedir/) file, and the hub leaves tagged
folders out of the saved workspace. A notebook with a React view and an HTML
view saves about 3 MB: the view sources plus their built revisions. The first
build in a new session downloads the view's packages again.

Studio edits view projects inside the sandbox workspace, so that workspace must
use [supported storage](../reference/compatibility.md#workspace-storage). Hub
backends that copy the workspace into the sandbox meet that requirement. The
Cloudflare backend mounts the workspace bucket into the sandbox with
[s3fs](https://github.com/s3fs-fuse/s3fs-fuse) instead, and Studio stops view
creation and builds there with a concurrent-change error.

## Add Studio to the notebook

In the project's notebook list, open the notebook's actions menu, choose
**Browse files**, and open `notebook.py`. Add this header at the top of the file
and click **Save**:

```python
# /// script
# dependencies = ["marimo-studio>=0.3.0"]
#
# [tool.marimo-studio]
# default = "dashboard"
# view_root = "studio"
# ///
```

![Browse files with the Studio header added to notebook.py](/screenshots/marimohub/notebook-header.png){width=520}

The header is a [PEP 723](https://peps.python.org/pep-0723/) script block,
which stores dependencies and tool configuration inside the notebook file:

| Entry          | Effect in marimohub                                                                                                              |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `dependencies` | The hub [installs inline dependencies](https://marimohub.docs.marimo.io/sandbox-image#inline-dependencies) when a sandbox starts |
| `default`      | Names the view that **Add view** proposes and that an app link without a view path serves                                        |
| `view_root`    | Stores view projects in `studio/` beside the notebook, where **Browse files** and a synced Git repository show them              |

The **HTML document** starter needs no extra packages. React, Svelte, Reveal.js
slides, and Notebook Kit starters need `marimo-studio[deno]>=0.3.0` in
`dependencies` and network access to the npm registry. The **Quarto document**
starter runs the `quarto` command, so the sandbox image must provide Quarto
1.9.38 or newer on `PATH`.

**Browse files** is read-only while an editor session runs, so stop the session
first. The saved header creates a new notebook version. Dependency changes apply
at the next sandbox start, and the first start after adding Studio spends extra
time installing it. For a Git-synced notebook, add the header in the repository
and sync again.

Studio 0.3 runs on marimo 0.25.1, so the sandbox image must provide that marimo
version. See
[Supported environment](../reference/compatibility.md#supported-environment).

To bring a new notebook into the hub, save the header in a local `notebook.py`
and choose that file under **Start from a file** in the **New Notebook** dialog.

## Create the first view

Open the notebook. The hub page shows the native marimo editor with an
**Add view** button in the Studio toolbar. Run the notebook's cells, click
**Add view**, keep the proposed name `dashboard`, choose **HTML document**, and
click **Create view**.

![The Add view dialog proposing dashboard with the HTML document starter selected](/screenshots/marimohub/add-view.png){width=450}

Notebook and Preview open side by side. Controls in Preview drive the same
kernel as the notebook, so moving a slider in the view reruns the dependent
cells and updates both panes.

View creation also rewrites the notebook header. It pins a Studio version
range to the installed version, for example `marimo-studio==0.3.0`, and records
aliases for the cells the starter placed. A direct reference such as
`marimo-studio @ https://example.com/marimo_studio-0.3.0-py3-none-any.whl` stays
as written, so the next sandbox installs the same build. The hub saves those
changes with `notebook.py`.

Continue with [Edit and preview in Studio](work-in-studio.md) and
[Place notebook results in a view](notebook-results.md) to shape the page.

## Check the saved view project

Stop the session from the hub's session menu when you finish. The hub saves
`notebook.py` and the workspace, and **Browse files** shows the view project:

```text
notebook.py
pyproject.toml
studio/
  dashboard/
    AGENTS.md
    index.html
    view.toml
```

![Browse files showing studio/dashboard/view.toml in the notebook workspace](/screenshots/marimohub/workspace-files.png)

The next session restores `studio/` into a fresh sandbox and opens Studio on the
`dashboard` view with its saved source.

## Run the view as an app

Choose **Open**, then **Run as app**. The hub starts the notebook with
`marimo run`, and Studio serves the view the editor shows.

![The dashboard view served as the notebook's marimohub app](/screenshots/marimohub/run-as-app.png)

The hub mirrors the path of its notebook frame into the `__mh_path` query
parameter, so a reload, **Copy URL**, **Run as app**, and app links reopen the
same view. For example, `/app/sales?__mh_path=report%2F` opens the `report`
view of the app named `sales`. An app link without `__mh_path` serves the
default view.

An app builds a view's production revision the first time a visitor opens it.
With `MARIMOHUB_PERSIST_WORKSPACE=workspace`, build that revision for a React,
Svelte, Reveal.js, or Notebook Kit view before you stop the editor session, and
the app serves it without a build. Run this code through the hub's MCP
`execute_code` or `marimo pair`, as
[Coding agents in marimohub](#coding-agents-in-marimohub) shows:

```python
import marimo_studio

await marimo_studio.agent.current_workspace().view("dashboard").build(
    profile="production"
)
```

[Run or export a view](run-and-share.md) covers runtimes and static export for
the same view outside the hub.

## Serve Preview behind a sign-in

Preview runs view code in a sandboxed frame with an opaque origin, so its
requests carry no cookies. A sign-in that checks a cookie on every request
rejects them, and after 10 seconds Preview reports
**The preview cannot reach the Studio server.**

`MARIMOHUB_SANDBOX_EXPOSURE` sets where the hub serves each sandbox:

| Exposure              | Sandbox address               | Preview                      |
| --------------------- | ----------------------------- | ---------------------------- |
| `subdomain` (default) | Its own domain                | Fails behind a login proxy   |
| `proxy`               | Hub origin, `/proxy/<token>/` | Works behind the hub sign-in |

With proxy exposure, notebook output already runs on the hub origin, which is
why the hub requires `MARIMOHUB_SANDBOX_PROXY_ACK_UNTRUSTED=true`. Studio reads
the exposure from the hub's
[sandbox context](../reference/configuration.md#marimohub-sandbox-context) and
serves Server runtime views on that origin too, where requests carry the hub
sign-in cookie.

Behind a login proxy on the sandbox domain, add
`MARIMO_STUDIO_TRUSTED_SERVER_RUNTIME=1` to the project's **Environment
variables** integration, then restart the session. Server runtime code then
runs on the sandbox origin with its cookies, local storage, and same-origin
requests. With proxy exposure, set it to `0` to keep Server runtime views in
their opaque frame. See
[Process settings](../reference/configuration.md#process-settings).

## Coding agents in marimohub

Coding agents author views through Studio's agent API in the live notebook
kernel. In a marimohub session, `workspace.status()` reports in `persistence`
whether the hub saves view files. In code mode, `view.preview_url()` returns
the view's address on the sandbox's public URL. `MARIMOHUB_SANDBOX_AUTH=on`
makes marimo in each sandbox require an access token, and the exposure decides
who can open that URL:

| Exposure and sandbox authentication | Who can open the preview URL                                       |
| ----------------------------------- | ------------------------------------------------------------------ |
| `proxy`                             | People signed in to the hub who can open the session               |
| `subdomain` with `on`               | Browsers signed in to the session's marimo server                  |
| `subdomain` with `off`, the default | Anyone with the URL, who can then run code in the session's kernel |

Open the preview URL in your own browser, and share the notebook page with
other people.

### Agents in the sandbox

[VS Code and OpenCode surfaces](https://marimohub.docs.marimo.io/surfaces) run
beside marimo in the edit sandbox. The hub gives their terminals and agents the
kernel's address in `MARIMOHUB_KERNEL_URL` and its access token file in
`MARIMOHUB_KERNEL_TOKEN_FILE`, which is empty when sandbox authentication is
off. Pass both to `marimo pair` on every call:

```console
kernel_args=(--url "$MARIMOHUB_KERNEL_URL")
if [[ -n "${MARIMOHUB_KERNEL_TOKEN_FILE:-}" ]]; then
  kernel_args+=(--token-file "$MARIMOHUB_KERNEL_TOKEN_FILE")
fi
uv run --no-sync marimo pair execute "${kernel_args[@]}" --code-file - <<'PY'
import marimo_studio
print(await marimo_studio.agent.current_workspace().status())
PY
```

The hub owns the session's marimo server. Attach to it through `marimo pair`,
and start no other server. Continue with
[Author with a coding agent](coding-agents.md).

### Agents over MCP

A coding agent connected to the hub's
[MCP server](https://marimohub.docs.marimo.io/mcp) edits views through the same
kernel. `start_session` opens an edit session, and `execute_code` runs Studio's
agent API in it:

```python
import marimo_studio

view = marimo_studio.agent.current_workspace().view("dashboard")
document = await view.read("index.html")
updated = document.content.replace("<h1>Dashboard</h1>", "<h1>Revenue</h1>")
await view.write("index.html", updated, expected_revision=document.revision)
build = await view.build()
print(build.revision, (await view.inspect()).freshness)
```

The printed freshness is `current` after a successful build, and an open
notebook page shows the new heading in Preview.

`start_session` initializes the kernel without a browser when the deployment
sets `MARIMOHUB_SANDBOX_AUTH=on`. Otherwise it reports `awaiting_client`, and
the notebook page must load once before `execute_code` runs. `view.show()` needs
an open notebook page, because it switches that page's Studio workspace to the
view.

## Troubleshoot

| Symptom                                                           | Fix                                                                                                                                         |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| The notebook page shows the marimo editor with no Studio toolbar  | Check that `dependencies` lists `marimo-studio`, then stop and restart the session                                                          |
| **Add view** warns that view files are lost when the session ends | Set `MARIMOHUB_PERSIST_WORKSPACE=workspace` on the hub. For a Git-synced notebook, commit `notebook.py` and the view folder before you stop |
| **Run as app** shows the notebook instead of the view             | Run mode serves the notebook as a marimo app while the view root contains no view. See [Persist view projects](#persist-view-projects)      |
| A starter asks for `marimo-studio[deno]`                          | Change the dependency to `marimo-studio[deno]>=0.3.0` and restart the session                                                               |
| Preview reports **The preview cannot reach the Studio server.**   | See [Serve Preview behind a sign-in](#serve-preview-behind-a-sign-in)                                                                       |
