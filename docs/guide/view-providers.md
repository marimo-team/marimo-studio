---
title: Add a view provider
description: Bring your own frontend framework or build tool to the New view picker with a Python package.
---

# Add a view provider

A view provider is a small Python package that adds starters to Studio's **New
view** picker. Install one in the notebook's environment, and its starters
appear beside the built-in HTML, React, Svelte, and Notebook Kit starters:

![The New view picker lists Acme report and Acme dashboard under From acme-views, above the built-in starters from marimo-studio](/screenshots/provider-new-view.png){width=448}

This page builds `acme-views`, the package in that picker. **Acme report**
starts a plain HTML page and needs Python alone. **Acme dashboard** adds a
[Lit](https://lit.dev/) component bundled by Vite. Each view stays an ordinary
frontend project, so people and coding agents edit it with that framework's own
files and commands.

::: warning Advanced feature
The view provider API is an advanced extension point. A future release may
change it to reduce the code a provider needs, and Studio plans to ship a
dedicated agent skill for writing providers. Studio requires an exact
`PROVIDER_API_VERSION` match, so pin `marimo-studio` to the minor line you
test, such as `marimo-studio>=0.2.3,<0.3`.
:::

## Ask a coding agent

A coding agent can build a provider from this page. Open one in the notebook's
project and paste this prompt:

```text
Read https://marimo-team.github.io/marimo-studio/guide/view-providers.md
and https://marimo-team.github.io/marimo-studio/reference/provider-api.md.

Create the guide's acme-views package in ./acme-views for analysis.py, with
the Acme report starter and the Acme dashboard starter, a Vite page with a
Lit header and every output cell. Follow "Add a framework build" and the
"Provider rules". Install the package with `uv add --editable ./acme-views`,
run every command in "Verify the provider", and fix each failure before
you stop.
```

To target another framework, replace `Lit` in the prompt with its name.
[Swap Lit for a JSX framework](#swap-lit-for-a-jsx-framework) lists what
changes. The rest of the page builds the same package by hand.

## What a provider decides

Pick **Acme report**, name the view `briefing`, and Studio creates a view
project beside the notebook:

```text
__marimo__/studio/analysis/briefing/
  view.toml    names the provider that owns this view
  index.html   the page, with one <marimo-cell> host per output cell
  AGENTS.md    instructions for coding agents that edit this view
```

Studio writes `view.toml`. The provider writes everything else and decides how
Studio treats each file. A **Source document** appears in Studio's Source
panel, where people and agents edit it. A **build input** is a file whose
change rebuilds the page.

| File         | Written by                  | Source document     | Build input |
| ------------ | --------------------------- | ------------------- | ----------- |
| `index.html` | the provider, at creation   | yes                 | yes         |
| `AGENTS.md`  | the provider, at creation   | yes                 | no          |
| `DESIGN.md`  | the user or an agent, later | yes, once it exists | no          |

`AGENTS.md` tells a coding agent how the project fits together: which file
holds the page, what the `<marimo-cell>` hosts mean, and where decisions
belong. The `marimo-studio` agent skill reads it before editing a view, so a
provider ships one written for its framework.

`DESIGN.md` records lasting decisions such as audience, visual direction, and
interaction priorities. Starters leave it out. The user or an agent adds it
once the view has a direction, and agents read it before styling.

Neither Markdown file shapes the built page, so editing them never triggers a
rebuild.

Studio calls the provider at four moments, and
[Write the provider](#write-the-provider) covers each one:

| When                                            | Studio calls                   |
| ----------------------------------------------- | ------------------------------ |
| Someone opens the **New view** picker           | `availability()`, `starters()` |
| Someone creates a view                          | `create()`                     |
| Source opens, or a watched file changes         | `inspect()`                    |
| Preview, run mode, or export needs a fresh page | `build()`                      |

## How Studio finds the provider

The package advertises the provider through the `marimo_studio.view_provider`
[entry point group](https://packaging.python.org/en/latest/specifications/entry-points/),
the Python packaging mechanism that lets an installed package publish objects
to other packages. Studio turns that registration into the names people see:

| Name         | Value                            | Made from                               |
| ------------ | -------------------------------- | --------------------------------------- |
| Registration | `report = "acme_views:provider"` | Entry point in the `acme-views` package |
| Provider key | `acme-views/report`              | Distribution name and registration name |
| Starter ID   | `acme-views/report:default`      | Provider key and the starter's key      |
| View record  | `provider = "acme-views/report"` | Written to `view.toml` at creation      |

Studio reads the entry points once per process, from the Python environment it
runs in. Restart `marimo edit` after you install a provider or change its
starters. When a provider reports itself unavailable, the picker disables its
starters and shows the recovery action it returned.

## Create the package

From the notebook's project, create a library with
[uv](https://docs.astral.sh/uv/), the Python package manager Studio uses to
resolve notebook environments:

```console
uv init --lib acme-views
cd acme-views
uv add "marimo-studio>=0.2.3,<0.3"
```

When the notebook's directory is a uv project, `uv init` adds `acme-views` to
its workspace. Register the provider in `acme-views/pyproject.toml`:

```toml
[project.entry-points."marimo_studio.view_provider"]
report = "acme_views:provider"
```

## Write the provider

Replace `src/acme_views/__init__.py` with:

```python
import html
from html.parser import HTMLParser
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    PROVIDER_API_VERSION,
    BuildRequest,
    BuildResult,
    CellSpec,
    InspectionRequest,
    MountDeclaration,
    NotebookSpec,
    ProjectInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    SourceLocation,
    StarterContext,
    StarterPlan,
    ViewProject,
    mount_attribute,
)

ENTRY = PurePosixPath("index.html")
AGENTS = PurePosixPath("AGENTS.md")
DESIGN = PurePosixPath("DESIGN.md")
MANIFEST = PurePosixPath("view.toml")
TAG = "<marimo-cell"

AGENTS_SOURCE = """# Acme view

Studio builds this view from `index.html` with the Acme provider.

- Each `<marimo-cell name="...">` in `index.html` shows the notebook cell with
  that name. Move or remove hosts freely and keep their `name` values.
- Keep calculations in the notebook, and layout and wording in this project.
- Record audience and visual decisions in `DESIGN.md`.
"""


class CellHosts(HTMLParser):
    """Collect each <marimo-cell name="..."> host with its source position."""

    def __init__(self, source: str) -> None:
        super().__init__()
        self.hosts: list[tuple[str, int, int]] = []
        self.feed(source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "marimo-cell" and (name := dict(attrs).get("name")):
            line, offset = self.getpos()
            self.hosts.append((name, line, offset + 1))


def enabled_cells(notebook: NotebookSpec) -> list[CellSpec]:
    """Return ordinary cells that run: neither disabled nor below a disabled cell."""
    cells = notebook.by_ref()
    disabled = {cell.ref for cell in notebook.cells if cell.config.disabled}
    pending = list(disabled)
    while pending:
        for child in cells[pending.pop()].downstream:
            if child not in disabled:
                disabled.add(child)
                pending.append(child)
    return [
        cell
        for cell in notebook.cells
        if cell.kind == "cell" and cell.ref not in disabled
    ]


def instrument(source: str, mounts: tuple[MountDeclaration, ...]) -> str:
    """Add Studio's mount attribute to each declared <marimo-cell> host."""
    lines = source.splitlines(keepends=True)
    for site in reversed(mounts):
        name, value = mount_attribute(site.id)
        row = site.source.line - 1
        cut = site.source.column - 1 + len(TAG)
        lines[row] = f'{lines[row][:cut]} {name}="{value}"{lines[row][cut:]}'
    return "".join(lines)


class ReportProvider:
    info = ProviderInfo(
        title="Acme report",
        summary="One HTML page with the notebook's output cells.",
        api_version=PROVIDER_API_VERSION,
    )
    starter = ProviderStarter(
        key="default",
        title="Acme report",
        summary="Start from one HTML page with every output cell.",
        documents=(ENTRY, AGENTS),
    )

    def availability(self, project: ViewProject | None = None) -> ProviderAvailability:
        return ProviderAvailability(True)

    def starters(self) -> tuple[ProviderStarter, ...]:
        return (self.starter,)

    def create(self, starter: ProviderStarter, context: StarterContext) -> StarterPlan:
        cells = tuple(
            context.cell_targets[cell.ref]
            for cell in enabled_cells(context.notebook)
            if cell.may_display_output
        )
        hosts = "\n".join(
            f'      <marimo-cell name="{html.escape(item.target)}"></marimo-cell>'
            for item in cells
        )
        page = f"""<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>{html.escape(context.view_name)}</title></head>
  <body>
    <main id="app-shell">
{hosts}
    </main>
  </body>
</html>
"""
        files = {ENTRY: page.encode(), AGENTS: AGENTS_SOURCE.encode()}
        return StarterPlan(files=files, cell_targets=cells)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        root = request.project.root
        source = (root / ENTRY).read_text(encoding="utf-8")
        mounts = tuple(
            MountDeclaration(
                id=f"cell-{index}",
                kind="cell",
                source=SourceLocation(ENTRY, line, column),
                allowed_targets=(name,),
            )
            for index, (name, line, column) in enumerate(CellHosts(source).hosts)
        )
        documents = [
            SourceDocument(ENTRY, "html", "edit"),
            SourceDocument(AGENTS, "markdown", "edit"),
        ]
        if (root / DESIGN).is_file():
            documents.append(SourceDocument(DESIGN, "markdown", "edit"))
        return ProjectInspection(
            editor_documents=tuple(documents),
            input_scope=(ProjectInput(ENTRY, "file"), ProjectInput(MANIFEST, "file")),
            mounts=mounts,
            diagnostics=(),
            build_fingerprint="acme-report-v1",
        )

    def build(self, request: BuildRequest) -> BuildResult:
        source = (request.project.root / ENTRY).read_text(encoding="utf-8")
        page = instrument(source, request.inspection.mounts)
        (request.staging_root / ENTRY).write_text(page, encoding="utf-8")
        return BuildResult(ENTRY, ())


provider = ReportProvider()
```

`ReportProvider` answers the four moments from
[What a provider decides](#what-a-provider-decides), one method at a time.

### `availability()` and `starters()`: fill the picker

When someone opens **New view**, Studio asks each provider whether it can run
and which starters it offers. `ReportProvider` needs nothing beyond Python, so
`availability()` always returns `ProviderAvailability(True)`.

`starters()` returns one `ProviderStarter`. Its `title` and `summary` become
the card in the picker, and `documents` becomes the **Files created** list.
Studio keeps the starter list for the life of the process.

### `create()`: write the starting files

`create()` runs once, when someone clicks **Create**. It receives the saved
notebook in `context.notebook` and returns every file of the new project in a
`StarterPlan`. `ReportProvider` writes one `<marimo-cell>` host into
`index.html` for each cell that may display output, and adds `AGENTS.md`.

`enabled_cells()` leaves out disabled cells and every cell downstream of one,
because marimo never runs a cell whose inputs come from a disabled cell. The
built-in starters apply the same rule.

`context.cell_targets` supplies the name each host uses. A named cell such as
`summary` keeps its name. For an unnamed cell, Studio proposes an alias such as
`cell-2` and saves it in the notebook when the provider returns that target in
`StarterPlan.cell_targets`.

### `inspect()`: describe the project

Studio calls `inspect()` whenever it needs the project's current shape: when
Source opens, when a watched file changes, and before each build. The
`ProjectInspection` it returns has three parts.

`editor_documents` fills the Source tabs with `index.html`, `AGENTS.md`, and
`DESIGN.md` once that file exists. `input_scope` names the build inputs,
`index.html` and `view.toml`. Studio rebuilds when one of them changes, which is
why edits to the Markdown files leave the page alone.

`mounts` holds one entry per `<marimo-cell>` host. A mount lets that spot in
the page show exactly the cell it names. `CellHosts` records each host's line
and column, so Studio can point an error at the right place in Source.

### `build()`: publish the page

`build()` runs when Preview, run mode, or export needs a page for the current
files. `request.project.root` holds a snapshot of the build inputs.
`ReportProvider` reads `index.html`, adds the attribute from
`mount_attribute()` to each host so Studio can connect it to the notebook, and
writes the result to `request.staging_root`. The `index.html` in Source keeps
its original markup.

Studio validates the staged files and publishes them as a new revision. A
failed build leaves the last good revision in Preview.

## Install it and create a view

From the notebook's project, install the package and ask Studio what it sees:

```console
uv add --editable ./acme-views
uv run marimo-studio doctor acme-views/report
```

```text
available acme-views/report
  distribution acme-views
  registration report
  installed 0.1.0
  One HTML page with the notebook's output cells.
  starters acme-views/report:default
```

`installed` reports the version of `acme-views`.

Start `uv run marimo edit analysis.py`, open the view menu, and choose **New
view**. **Acme report** waits under **From acme-views**, and **Files created**
lists `index.html, AGENTS.md`. The CLI creates the same view:

```console
uv run marimo-studio view create briefing \
  --target analysis.py \
  --starter acme-views/report:default
```

Open Source to see the provider's choices. The page holds one host per output
cell. Now give the view a design direction by saving
`__marimo__/studio/analysis/briefing/DESIGN.md`:

```md
# Design

Audience: the weekly operations review.
Lead with the threshold control, then its result.
```

Studio lists `DESIGN.md` the next time it inspects the view, such as after the
next save of `index.html`:

![Source panel for the briefing view with index.html, AGENTS.md, and DESIGN.md tabs, showing marimo-cell hosts named cell-2 and summary](/screenshots/provider-source.png){width=696}

Every environment that edits, builds, or exports the view needs the provider
package. Publish it to a package index, or declare it as a path or Git source in
the notebook's project, so `uv` can install it wherever the notebook runs.

## Add a framework build

**Acme dashboard** bundles a Lit component with [Vite](https://vite.dev/), a
frontend build tool. Vite needs a JavaScript runtime, and the machine that
opens the notebook may lack Node.js and `npx`. [Deno](https://deno.com/) fills
that role. It is a JavaScript and TypeScript runtime that also installs npm
packages, and it ships on PyPI as the [`deno`](https://pypi.org/project/deno/)
package. Declared as a Python dependency, it lands in the same environment as
Studio, and `deno.find_deno_bin()` returns its path. The built-in React,
Svelte, and Notebook Kit providers use the same package.

Add the dependency from `acme-views` and register a second provider:

```console
uv add deno
```

```toml
[project.entry-points."marimo_studio.view_provider"]
report = "acme_views:provider"
vite = "acme_views.vite:provider"
```

### Pin the dashboard's npm packages

The dashboard starter copies three files into every new view. Keep them in the
package, in `src/acme_views/dashboard/`.

`main.js` defines the Lit header:

```js
import { html, LitElement } from "lit";

customElements.define(
  "acme-header",
  class extends LitElement {
    render() {
      return html`<h1>Acme dashboard</h1>`;
    }
  },
);
```

`deno.json` pins Lit and Vite:

```json
{
  "nodeModulesDir": "auto",
  "imports": {
    "lit": "npm:lit@3.3.1",
    "vite": "npm:vite@7.1.7"
  }
}
```

Generate `deno.lock` beside them:

```console
cd src/acme_views/dashboard
uv run -- deno install --lockfile-only
```

The lockfile records the exact version and checksum of every package in the
dependency tree, including packages that Lit and Vite pull in. Rerun the command
after you change `deno.json`.

### Write the Vite provider

Create `src/acme_views/vite.py`:

```python
import os
import shutil
from dataclasses import replace
from importlib.resources import files
from pathlib import Path, PurePosixPath

from deno import find_deno_bin
from marimo_studio.view_providers import (
    PROVIDER_API_VERSION,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectDiagnostic,
    ProjectInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderCommandResult,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    StarterContext,
    StarterPlan,
    ViewProject,
)

from acme_views import AGENTS, ENTRY, ReportProvider, instrument

MAIN = PurePosixPath("main.js")
CONFIG = PurePosixPath("deno.json")
LOCK = PurePosixPath("deno.lock")
TEMPLATE = files("acme_views") / "dashboard"


def installed(work: Path, pattern: str) -> str:
    """Return the resolved paths of installed npm files that match `pattern`."""
    paths = sorted((work / "node_modules" / ".deno").glob(pattern))
    if not paths:
        raise FileNotFoundError(f"deno install provided no {pattern}")
    return ",".join(str(path.resolve()) for path in paths)


def failure(step: str, result: ProviderCommandResult) -> BuildResult:
    diagnostic = ProjectDiagnostic(
        code="vite-build-failed",
        severity="error",
        message=f"{step} failed with exit code {result.returncode}.",
        hint=result.stderr.strip()[-2000:],
    )
    return BuildResult(None, (diagnostic,))


class ViteProvider(ReportProvider):
    info = ProviderInfo(
        title="Acme Vite",
        summary="A Vite page with Lit components and the notebook's output cells.",
        api_version=PROVIDER_API_VERSION,
    )
    starter = ProviderStarter(
        key="default",
        title="Acme dashboard",
        summary="Start from a Vite page with a Lit header and every output cell.",
        documents=(ENTRY, AGENTS, MAIN, CONFIG, LOCK),
    )

    def availability(self, project: ViewProject | None = None) -> ProviderAvailability:
        try:
            find_deno_bin()
        except FileNotFoundError:
            return ProviderAvailability(
                False,
                reason="deno-missing",
                action="Install the deno package where Studio runs.",
            )
        return ProviderAvailability(True)

    def create(self, starter: ProviderStarter, context: StarterContext) -> StarterPlan:
        plan = super().create(starter, context)
        page = plan.files[ENTRY].decode()
        page = page.replace(
            '<main id="app-shell">\n',
            '<main id="app-shell">\n      <acme-header></acme-header>\n',
        ).replace(
            "  </body>",
            '    <script type="module" src="./main.js"></script>\n  </body>',
        )
        project_files = {**plan.files, ENTRY: page.encode()}
        for path in (MAIN, CONFIG, LOCK):
            project_files[path] = (TEMPLATE / path.name).read_bytes()
        return StarterPlan(files=project_files, cell_targets=plan.cell_targets)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        inspection = super().inspect(request)
        return replace(
            inspection,
            editor_documents=(
                *inspection.editor_documents,
                SourceDocument(MAIN, "javascript", "edit"),
                SourceDocument(CONFIG, "json", "edit"),
                SourceDocument(LOCK, "json", "read"),
            ),
            input_scope=(
                *inspection.input_scope,
                ProjectInput(MAIN, "file"),
                ProjectInput(CONFIG, "file"),
                ProjectInput(LOCK, "file"),
            ),
            build_fingerprint="acme-vite-v1",
        )

    def build(self, request: BuildRequest) -> BuildResult:
        work = (request.staging_root.parent / "work").resolve()
        output = request.staging_root.resolve()
        for path in request.inputs:
            (work / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(request.project.root / path, work / path)
        source = (work / ENTRY).read_text(encoding="utf-8")
        page = instrument(source, request.inspection.mounts)
        (work / ENTRY).write_text(page, encoding="utf-8")

        deno = find_deno_bin()
        cache = {"DENO_DIR": str(request.cache_root / "deno")}
        result = request.runner.run(
            [deno, "install", "--frozen"],
            cwd=work,
            environment={**os.environ, **cache},
        )
        if result.returncode != 0:
            return failure("deno install", result)

        # Stop Vite's package and workspace search at the working directory.
        (work / "package.json").write_text('{ "private": true }\n', encoding="utf-8")
        (work / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
        vite = [
            deno,
            "run",
            "--cached-only",
            "--frozen",
            "--no-prompt",
            f"--allow-read={work},{output}",
            f"--allow-write={output}",
            "--allow-env",
            "--allow-sys=uid,osRelease",
            f"--allow-ffi={installed(work, '@rollup+rollup-*/**/*.node')}",
            f"--allow-run={installed(work, '@esbuild+*/**/esbuild*')}",
            "node_modules/vite/bin/vite.js",
            "build",
            "--configLoader=native",
            "--base",
            "./",
            "--outDir",
            str(output),
        ]
        result = request.runner.run(vite, cwd=work, environment=cache)
        if result.returncode != 0:
            return failure("vite build", result)
        return BuildResult(ENTRY, ())


provider = ViteProvider()
```

`ViteProvider` reuses the report provider and changes four methods:

- `availability()` checks for the `deno` binary, so the picker disables the
  starter with a recovery action when it is missing.
- `create()` copies `main.js`, `deno.json`, and `deno.lock` into the new view,
  and adds an `<acme-header>` element and a `<script>` tag to `index.html`.
- `inspect()` adds the three files to Source and to the build inputs.
  `deno.lock` opens read-only.
- `build()` copies the inputs to a working directory beside
  `request.staging_root` and adds the mount attributes there. `deno install
--frozen` installs exactly the locked packages into `node_modules`, and fails
  when `deno.json` and `deno.lock` disagree. Vite then bundles `main.js` into
  `request.staging_root`.

Studio deletes the working directory after each build. `DENO_DIR` keeps Deno's
downloads in `request.cache_root`, which persists between builds. The first
build downloads Vite and Lit, and later builds reuse them.
`request.runner.run()` stops a command when Studio cancels the build, and every
command in one build shares a 120-second budget. A nonzero exit becomes a
diagnostic that `marimo-studio view build` prints.

### Sandbox the build

npm packages run code inside Vite, so `build()` gives Vite only the
[Deno permissions](https://docs.deno.com/runtime/fundamentals/security/) a
build needs. Deno denies everything else, including network access and files
outside the build:

| Flag                                        | Allows                                        |
| ------------------------------------------- | --------------------------------------------- |
| `--allow-read` with the work and output     | reading the working copy and the built files  |
| `--allow-write` with the output             | writing the built page                        |
| `--allow-env`, `--allow-sys=uid,osRelease`  | the environment and system details Vite reads |
| `--allow-ffi` with Rollup's `.node` binding | loading Rollup's native bundler               |
| `--allow-run` with the esbuild binary       | starting esbuild, which transforms the code   |

The Vite command receives `DENO_DIR` as its whole environment, so tokens and
other variables from the Studio process stay out of the build. `--cached-only`
and `--frozen` limit it to the packages that `deno install` placed. The
`package.json` and `pnpm-workspace.yaml` that `build()` writes stop Vite from
reading parent directories while it looks for a project root, and
`--configLoader=native` loads a `vite.config.js` without writing a temporary
file.

### Swap Lit for a JSX framework

To build the dashboard header with [Preact](https://preactjs.com/) in place of
Lit, change the starter in four places:

- Name the entry module `main.jsx`, point the `<script>` tag at it, and list it
  with the `javascriptreact` language.
- Add `vite.config.js` to `src/acme_views/dashboard/`, the files `create()`
  copies, `ProviderStarter.documents`, `editor_documents`, and `input_scope`:

  ```js
  export default { esbuild: { jsx: "automatic", jsxImportSource: "preact" } };
  ```

- Replace Lit with `"preact": "npm:preact@10.27.2"` in `deno.json` and
  regenerate `deno.lock`. Vite resolves subpaths such as `preact/hooks` from
  the `node_modules` directory that `deno install` creates.
- Render components into their own element, such as `<div id="acme-header">`.
  Keep the `<marimo-cell>` hosts outside the component tree so the framework
  never replaces them.

`CellHosts` looks for hosts in `index.html`. To place `marimo-cell`,
`marimo-output`, or `mo-value` hosts inside components, extend `inspect()` to
find them there. The built-in providers in
[`view_providers/_bundled`](https://github.com/marimo-team/marimo-studio/tree/main/packages/marimo-studio/src/marimo_studio/view_providers/_bundled)
find hosts in JSX and Svelte.

## Provider rules

Studio validates most of these rules and reports the one a result breaks.

- Implement every method as a synchronous function. Set
  `info.api_version = PROVIDER_API_VERSION`.
- Leave `view.toml`, `.artifacts/`, `.locks/`, and `.gitignore` out of
  `StarterPlan.files`. Studio writes those paths.
- List `view.toml` in `input_scope` and leave it out of `editor_documents`.
- List every file the build reads in `input_scope`. The build snapshot holds
  those files and nothing else from the view project.
- Keep `inspect()` read-only. Put reusable data in `request.cache_root`.
- Give each mount a lowercase ID that is unique within the inspection and stays
  the same for the same host. Match `kind` to the host: `cell` for
  `marimo-cell`, `output` for `marimo-output`, `value` for an element with
  `mo-value`.
- Add `mount_attribute(site.id)` to each declared host in the built files.
- Write the build output inside `request.staging_root`. The entry document needs
  one `head`, one `body`, and one element with `id="app-shell"`.
- Run commands with `cwd` inside `request.project.root`. The working directory
  `request.staging_root.parent / "work"` qualifies.
- Pass `environment={**os.environ, ...}` to add variables. A mapping replaces
  the command's whole environment.
- Pin npm packages in a lockfile that ships with the starter, and install them
  with `deno install --frozen`.
- Run build tools that execute npm code with scoped Deno permissions, as in
  [Sandbox the build](#sandbox-the-build).
- Use a kebab-case diagnostic `code` and a non-empty `message` without leading
  or trailing whitespace.
- Change `build_fingerprint` when the provider's build output can change for
  the same inputs.

## Verify the provider

Run these from the notebook's project after every provider change:

```console
uv run marimo-studio doctor acme-views/vite
uv run marimo-studio starters
uv run marimo-studio view create dash --target analysis.py \
  --starter acme-views/vite:default --dry-run
uv run marimo-studio view create dash --target analysis.py \
  --starter acme-views/vite:default
uv run marimo-studio view build dash --target analysis.py
uv run marimo run analysis.py
```

| Command                     | Expected result                                                             |
| --------------------------- | --------------------------------------------------------------------------- |
| `doctor acme-views/vite`    | First line `available acme-views/vite`, exit status 0                       |
| `starters`                  | `available acme-views/vite:default`                                         |
| `view create ... --dry-run` | `Would create view dash` and every starter file                             |
| `view create`               | `Created view dash`                                                         |
| `view build`                | `Built dash for development use`                                            |
| `marimo run`                | `http://localhost:2718/dash/` shows the Lit header and the notebook's cells |

`marimo run` builds the `production` profile on the first request. The provider
works when `/dash/` shows the notebook's controls and outputs with no
`This section is unavailable.` placeholder.

## Troubleshoot

| Message or symptom                                                                                 | Fix                                                                                                        |
| -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `Unknown view provider 'acme-views/vite'`                                                          | Install the package in the environment that runs Studio, check the entry point, and restart `marimo edit`. |
| `View provider ... is not installed`, while `doctor` shows `uses API version 2. Studio requires 1` | Set `api_version=PROVIDER_API_VERSION` and pin the tested `marimo-studio` minor line.                      |
| `cannot expose Studio-owned 'view.toml' in the editor`                                             | Remove `view.toml` from `editor_documents`.                                                                |
| `must include Studio-owned 'view.toml' in its input scope`                                         | Add `ProjectInput(PurePosixPath("view.toml"), "file")`.                                                    |
| `Provider working directory is outside the view snapshot`                                          | Run commands in `request.project.root` or a directory beneath it.                                          |
| `expected one element with id="app-shell"`                                                         | Keep one `#app-shell` element in the entry document.                                                       |
| The page shows `This section is unavailable.` in place of a cell                                   | Add `mount_attribute(site.id)` to each declared host in `build()`.                                         |

The [View provider API](../reference/provider-api.md) defines every record,
including `marimo-output` and `mo-value` mounts, source-located diagnostics,
and provider options read from `view.toml`.
