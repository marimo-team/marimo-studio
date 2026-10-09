---
title: Add a view provider
description: Bring your own frontend framework or build tool to the New view picker with a Python package.
---

# Add a view provider

A view provider is a small Python package that adds starters to Studio's **New
view** picker. Install one in the notebook's environment, and its starters
appear beside the built-in HTML, React, Svelte, Notebook Kit, Quarto, Typst, and
LaTeX starters:

![The New view picker lists Acme report and Acme dashboard under From acme-views, above the built-in starters from marimo-studio](/screenshots/provider-new-view.png){width=448}

This page builds `acme-views`, the package in that picker. **Acme report**
starts a plain HTML page and needs Python alone. **Acme dashboard** adds a
[Lit](https://lit.dev/) component bundled by Vite. Each view stays an ordinary
frontend project, so people and coding agents edit it with that framework's own
files and commands.

::: warning Advanced feature
The view provider API is an advanced extension point. Pin `marimo-studio` to
the minor line you test, such as `marimo-studio>=0.4,<0.5`.
:::

## Choose a pattern

Every provider imports one module, `marimo_studio.view_providers`. Pick the
pattern closest to your tool, then follow its section and read the example
that uses it:

| Pattern                                                                | The build                                       | SDK pieces                                                  | Example                                                                                                                                            |
| ---------------------------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| [HTML page](#write-the-provider)                                       | copies or templates HTML                        | `html_sites`, `copy_inputs`                                 | this guide's `ReportProvider`                                                                                                                      |
| [Framework build](#add-a-framework-build)                              | bundles JavaScript with a pinned toolchain      | `request.runner`, `request.work_root`, `request.cache_root` | [`deno_react`](https://github.com/marimo-team/marimo-studio/tree/main/packages/marimo-studio/src/marimo_studio/view_providers/_builtin/deno_react) |
| [Command-line tool](../reference/provider-api.md#check-external-tools) | runs an installed tool that writes HTML         | `probe_tool`, `copy_inputs`, `ProviderError`                | [`quarto`](https://github.com/marimo-team/marimo-studio/tree/main/packages/marimo-studio/src/marimo_studio/view_providers/_builtin/quarto)         |
| [Rendered document](#publish-a-document)                               | renders a PDF, SVG, or PNG with notebook values | `RenderValue`, `RenderOutput`, `RenderCell`, `render()`     | [`typst`](https://github.com/marimo-team/marimo-studio/tree/main/packages/marimo-studio/src/marimo_studio/view_providers/_builtin/typst)           |

The Quarto provider imports only the public module, so its source shows that
pattern at full size. The Typst and LaTeX providers share a library for typeset
documents inside Studio, and the React, Svelte, and Notebook Kit providers share
a Deno library. When no pattern fits, start from the
HTML page provider and replace `build()` with your tool's steps.

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
| `view.toml`  | Studio                      | yes                 | yes         |

Studio lists `view.toml`, `AGENTS.md`, and `DESIGN.md` in Source and adds
`view.toml` to the build inputs for every provider.

`AGENTS.md` tells a coding agent how the project fits together: which file
holds the page, what the `<marimo-cell>` hosts mean, and where decisions
belong. The `marimo-studio` agent skill reads it before editing a view, so a
provider ships one written for its framework.

`DESIGN.md` records lasting decisions such as audience, visual direction, and
interaction priorities. Starters leave it out. The user or an agent adds it
once the view has a direction, and agents read it before styling.

Neither Markdown file shapes the built page, so editing them never triggers a
rebuild.

Studio calls the provider at these moments, and
[Write the provider](#write-the-provider) covers each one:

| When                                            | Studio calls                   |
| ----------------------------------------------- | ------------------------------ |
| Someone opens the **New view** picker           | `availability()`, `starters()` |
| Someone creates a view                          | `create()`                     |
| Source opens, or a watched file changes         | `inspect()`                    |
| Preview, run mode, or export needs a fresh page | `build()`                      |
| A rendered document's notebook results change   | `render()`                     |

## How Studio finds the provider

The package advertises the provider through the `marimo_studio.view_provider`
[entry point group](https://packaging.python.org/en/latest/specifications/entry-points/),
the Python packaging mechanism that lets an installed package publish objects
to other packages. Studio turns that registration into the names people see:

| Name         | Value                            | Made from                               |
| ------------ | -------------------------------- | --------------------------------------- |
| Registration | `report = "acme_views:provider"` | Entry point in the `acme-views` package |
| Provider key | `acme-views/report`              | Distribution name and registration name |
| Starter ID   | `acme-views/report:default`      | Provider key and the starter key        |
| `view.toml`  | `provider = "acme-views/report"` | Written to the view project at creation |

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
uv add "marimo-studio>=0.4,<0.5"
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
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    InspectionRequest,
    BuildInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    StarterContext,
    StarterPlan,
    copy_inputs,
    html_sites,
)

ENTRY = PurePosixPath("index.html")
AGENTS = PurePosixPath("AGENTS.md")

AGENTS_SOURCE = """# Acme view

Studio builds this view from `index.html` with the Acme provider.

- Each `<marimo-cell name="...">` in `index.html` shows the notebook cell with
  that name. Move or remove hosts freely and keep their `name` values.
- Keep calculations in the notebook, and layout and wording in this project.
- Record audience and visual decisions in `DESIGN.md`.
"""


class ReportProvider:
    info = ProviderInfo(
        title="Acme report",
        summary="One HTML page with the notebook's output cells.",
    )
    starter = ProviderStarter(
        key="default",
        title="Acme report",
        summary="Start from one HTML page with every output cell.",
        documents=(ENTRY, AGENTS),
    )

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(True)

    def starters(self) -> tuple[ProviderStarter, ...]:
        return (self.starter,)

    def create(self, starter: ProviderStarter, context: StarterContext) -> StarterPlan:
        cells = context.output_cells
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
        source = (request.project.root / ENTRY).read_bytes()
        sites, diagnostics = html_sites(ENTRY, source)
        return ProjectInspection(
            documents=(SourceDocument(ENTRY, "html", "edit"),),
            inputs=(BuildInput(ENTRY, "file"),),
            sites=sites,
            diagnostics=diagnostics,
        )

    def build(self, request: BuildRequest) -> BuildResult:
        copy_inputs(request, request.staging_root)
        return BuildResult(ENTRY)


provider = ReportProvider()
```

`ReportProvider` answers the page moments from
[What a provider decides](#what-a-provider-decides), one method at a time.
[Publish a document](#publish-a-document) adds `render()`.

### `availability()` and `starters()`: fill the picker

When someone opens **New view**, Studio asks each provider whether it can run
and which starters it offers. `ReportProvider` needs nothing beyond Python, so
`availability()` always returns `ProviderAvailability(True)`. A provider that
runs an installed tool returns `probe_tool(("tool", "--version"), minimum=...,
install=...)`, which reports a missing or outdated tool with your install
instructions.

`starters()` returns one `ProviderStarter`. Its `title` and `summary` become
the card in the picker, and `documents` becomes the **Files created** list.
Studio keeps the starter list for the life of the process.

### `create()`: write the starting files

`create()` runs once, when someone clicks **Create**. It receives the saved
notebook in `context.notebook` and returns every file of the new project in a
`StarterPlan`. `ReportProvider` writes one `<marimo-cell>` host into
`index.html` for each cell in `context.output_cells`, and adds `AGENTS.md`.

`context.output_cells` lists the cells that may display output. It leaves out
disabled cells and every cell downstream of one, because marimo never runs a
cell whose inputs come from a disabled cell. The built-in starters use the same
list.

`context.cell_targets` supplies the name each host uses. A named cell such as
`summary` keeps its name. For an unnamed cell, Studio proposes an alias such as
`cell-2` and saves it in the notebook when the provider returns that target in
`StarterPlan.cell_targets`.

### `inspect()`: describe the project

Studio calls `inspect()` whenever it needs the project's current shape: when
Source opens, when a watched file changes, and before each build. The
`ProjectInspection` it returns lists the project's documents, build inputs, and
projection sites.

`documents` lists the Source documents, here `index.html`, and Studio adds
`AGENTS.md` and `DESIGN.md` once they exist. `inputs` lists the build
inputs. Studio rebuilds when `index.html` or `view.toml` changes, which is why
edits to the Markdown files leave the page alone. For a project with many
files, `project_files(request.project)` lists every file that can affect a
build.

`sites` holds one projection site per `<marimo-cell>`, `<marimo-output>`, or
`mo-value` host. A site lets that spot in the page show exactly the result it
names. `html_sites()` records each host's line and column, so Studio can point
an error at the right place in Source, and returns a diagnostic for a malformed
host.

### `build()`: publish the page

`build()` runs when Preview, run mode, or export needs a page for the current
files. `request.project.root` holds a snapshot of the build inputs, and Studio
has already marked each site's host in the snapshot so it can connect the host
to the notebook. `ReportProvider` copies its inputs to
`request.staging_root` with `copy_inputs()`. The `index.html` in Source keeps its
original markup.

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
from dataclasses import replace
from importlib.resources import files
from pathlib import Path, PurePosixPath

from deno import find_deno_bin
from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    InspectionRequest,
    BuildInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderCommandResult,
    ProviderError,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    StarterContext,
    StarterPlan,
    copy_inputs,
)

from acme_views import AGENTS, ENTRY, ReportProvider

MAIN = PurePosixPath("main.js")
CONFIG = PurePosixPath("deno.json")
LOCK = PurePosixPath("deno.lock")
TEMPLATE = files("acme_views") / "dashboard"


def installed(work: Path, pattern: str) -> str:
    """Return the resolved paths of installed npm files that match `pattern`."""
    paths = sorted((work / "node_modules" / ".deno").glob(pattern))
    if not paths:
        raise ProviderError(f"deno install provided no {pattern}.")
    return ",".join(str(path.resolve()) for path in paths)


def check(step: str, result: ProviderCommandResult) -> None:
    if result.returncode != 0:
        raise ProviderError(
            f"{step} failed with exit code {result.returncode}: "
            f"{result.stderr.strip()[-2000:]}",
            hint="Fix the error in the view's source, then build again.",
            code="vite-build-failed",
        )


class ViteProvider(ReportProvider):
    info = ProviderInfo(
        title="Acme Vite",
        summary="A Vite page with Lit components and the notebook's output cells.",
    )
    starter = ProviderStarter(
        key="default",
        title="Acme dashboard",
        summary="Start from a Vite page with a Lit header and every output cell.",
        documents=(ENTRY, AGENTS, MAIN, CONFIG, LOCK),
    )

    def availability(self) -> ProviderAvailability:
        try:
            find_deno_bin()
        except FileNotFoundError:
            return ProviderAvailability(
                False,
                reason="The deno package is not installed.",
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
            documents=(
                *inspection.documents,
                SourceDocument(MAIN, "javascript", "edit"),
                SourceDocument(CONFIG, "json", "edit"),
                SourceDocument(LOCK, "json", "read"),
            ),
            inputs=(
                *inspection.inputs,
                BuildInput(MAIN, "file"),
                BuildInput(CONFIG, "file"),
                BuildInput(LOCK, "file"),
            ),
        )

    def build(self, request: BuildRequest) -> BuildResult:
        work = request.work_root.resolve()
        output = request.staging_root.resolve()
        copy_inputs(request, work)

        deno = find_deno_bin()
        cache = {"DENO_DIR": str(request.cache_root / "deno")}
        result = request.runner.run(
            [deno, "install", "--frozen"],
            cwd=work,
            environment={**os.environ, **cache},
        )
        check("deno install", result)

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
        check("vite build", request.runner.run(vite, cwd=work, environment=cache))
        return BuildResult(ENTRY)


provider = ViteProvider()
```

`ViteProvider` reuses the report provider and changes four methods:

- `availability()` checks for the `deno` binary, so the picker disables the
  starter with a recovery action when it is missing.
- `create()` copies `main.js`, `deno.json`, and `deno.lock` into the new view,
  and adds an `<acme-header>` element and a `<script>` tag to `index.html`.
- `inspect()` adds the three files to Source and to the build inputs.
  `deno.lock` opens read-only.
- `build()` copies the inputs to `request.work_root`, a private directory that
  Studio empties after the build. `deno install --frozen` installs exactly the
  locked packages into `node_modules`, and fails when `deno.json` and
  `deno.lock` disagree. Vite then bundles `main.js` into `request.staging_root` and keeps
  the site attributes on the hosts in `index.html`.

`DENO_DIR` keeps Deno's downloads in `request.cache_root`, which persists between builds. The first
build downloads Vite and Lit, and later builds reuse them.
`request.runner.run()` stops a command when Studio cancels the build, and every
command in one build shares a 120-second budget. `check()` raises
`ProviderError` for a nonzero exit, and `marimo-studio view build` prints it
with the end of the command's error output.

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
  copies, `ProviderStarter.documents`, and the inspection's `documents` and
  `inputs`:

  ```js
  export default { esbuild: { jsx: "automatic", jsxImportSource: "preact" } };
  ```

- Replace Lit with `"preact": "npm:preact@10.27.2"` in `deno.json` and
  regenerate `deno.lock`. Vite resolves subpaths such as `preact/hooks` from
  the `node_modules` directory that `deno install` creates.
- Render components into their own element, such as `<div id="acme-header">`.
  Keep the `<marimo-cell>` hosts outside the component tree so the framework
  never replaces them.

`html_sites()` finds hosts in `index.html`. To place `marimo-cell`,
`marimo-output`, or `mo-value` hosts inside components, extend `inspect()` to
report them as `ProjectionSite` records from the component source. The
built-in providers in
[`view_providers/_builtin`](https://github.com/marimo-team/marimo-studio/tree/main/packages/marimo-studio/src/marimo_studio/view_providers/_builtin)
find hosts in JSX and Svelte.

## Publish a document

A provider can publish a PDF, SVG, or PNG in place of a page. Its `build()`
returns a template, and Studio renders the template again whenever a notebook
value it reads changes. Studio shows each rendered document in a viewer page with a
download link.

Register `card = "acme_views.card:provider"`, then create
`src/acme_views/card.py`:

```python
from pathlib import PurePosixPath
from xml.sax.saxutils import escape

from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    InspectionRequest,
    BuildInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    RenderRequest,
    RenderValue,
    SourceDocument,
    SourceLocation,
    StarterContext,
    StarterPlan,
    copy_inputs,
)

CARD = PurePosixPath("card.svg")
TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="240" height="80">
  <text x="16" y="48">Total: {{ total }}</text>
</svg>
"""


class CardProvider:
    info = ProviderInfo(
        title="Acme card",
        summary="An SVG card with the notebook's report total.",
    )
    starter = ProviderStarter(
        key="default",
        title="Acme card",
        summary="Start from an SVG card that shows report.total.",
        documents=(CARD,),
    )

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(True)

    def starters(self) -> tuple[ProviderStarter, ...]:
        return (self.starter,)

    def create(self, starter: ProviderStarter, context: StarterContext) -> StarterPlan:
        return StarterPlan(files={CARD: TEMPLATE.encode()}, cell_targets=())

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        return ProjectInspection(
            documents=(SourceDocument(CARD, "xml", "edit"),),
            inputs=(BuildInput(CARD, "file"),),
            render_values=(RenderValue("report.total", SourceLocation(CARD, 2, 30)),),
        )

    def build(self, request: BuildRequest) -> BuildResult:
        copy_inputs(request, request.staging_root)
        return BuildResult(CARD)

    def render(self, request: RenderRequest) -> BuildResult:
        template = (request.template_root / request.document).read_text("utf-8")
        total = request.values.get("report.total")
        text = "pending" if total is None else str(total)
        card = template.replace("{{ total }}", escape(text))
        (request.output_root / CARD).write_text(card, encoding="utf-8")
        return BuildResult(CARD)


provider = CardProvider()
```

`render_values` names the notebook values the document reads, at the place it
reads them. Each arrives in its JSON form, so a dataframe arrives as a list of
row objects and a date as ISO 8601 text. A template that places figures
reports `render_outputs`, and one that places a named cell's output reports
`render_cells`. A build that knows where the template places each figure
returns those sizes in `BuildResult.output_sizes`, and Studio then draws each
figure at its size. Studio keeps the built template private and calls
`render()` with a writable copy in `request.template_root`, an empty
`request.output_root`, and the results the reader's notebook currently has. A
result without a current value is absent, and a null result is `None`, so the
template shows its default for both.
[Render documents with notebook values](../reference/provider-api.md#render-documents-with-notebook-values)
defines the contract.

## Provider rules

Studio checks each result against these rules and reports the rule it breaks.

- Implement every method as a synchronous function. Raise `ProviderError` for
  a problem the author can fix, and pass `source=` when it points at a file.
- Declare every provider option in `info.options`. Studio rejects a view whose
  `view.toml` sets any other option.
- List every file the build reads in `inputs`. The build snapshot holds
  those files and nothing else from the view project.
- Keep `inspect()` read-only. Put reusable data in `request.cache_root`.
- Report each host as a `ProjectionSite` whose `offset` points inside its start
  tag in the stored file. `html_sites()` does this for HTML. Match `kind` to the
  host: `cell` for `marimo-cell`, `output` for `marimo-output`, `value` for an
  element with `mo-value`.
- Build from the snapshot in `request.project.root` and keep the
  `data-marimo-studio-site` attribute on each host in the built files.
- Write the build output inside `request.staging_root`. An HTML entry document
  needs one `head`, one `body`, and one element with `id="app-shell"`.
- Run `build()` commands with `cwd` inside `request.project.root`, which holds
  `request.work_root` and `request.staging_root`. Run `render()` commands
  inside `request.template_root`.
- Pass `environment={**os.environ, ...}` to add variables. A mapping replaces
  the command's whole environment.
- Pin npm packages in a lockfile that ships with the starter, and install them
  with `deno install --frozen`.
- Run build tools that execute npm code with scoped Deno permissions, as in
  [Sandbox the build](#sandbox-the-build).
- Use a kebab-case diagnostic `code` and a non-empty `message` without leading
  or trailing whitespace.

Studio rebuilds a view when its inputs change, when the provider package's
version changes, or when `availability()` reports a new tool version. Release a
new version when the build output changes for the same inputs.

## Verify the provider

`check_provider()` runs each starter through the same steps as Studio and
raises `ProviderCheckError` with the message Studio would show. Add it to the
provider's tests:

```python
from marimo_studio.view_providers.testing import check_provider

from acme_views import provider


def test_report_provider() -> None:
    (view,) = check_provider(provider)
    assert "index.html" in {path.as_posix() for path in view.published}
```

Pass the provider object while you develop it, and the installed key, such as
`check_provider("acme-views/report")`, to load it the way Studio does. Pass
`options={"entrypoint": "page.html"}` to check a provider option.
[`check_provider()`](../reference/provider-api.md#check-provider) lists every
check.

Then check the installed provider from the notebook's project:

```console
uv run marimo-studio doctor acme-views/vite
uv run marimo-studio view create dash --target analysis.py \
  --starter acme-views/vite:default
uv run marimo-studio view build dash --target analysis.py
uv run marimo run analysis.py
```

| Command                  | Expected result                                                             |
| ------------------------ | --------------------------------------------------------------------------- |
| `doctor acme-views/vite` | First line `available acme-views/vite`, exit status 0                       |
| `view create`            | `Created view dash`                                                         |
| `view build`             | `Built dash for development use`                                            |
| `marimo run`             | `http://localhost:2718/dash/` shows the Lit header and the notebook's cells |

`marimo run` builds the `production` profile on the first request. The provider
works when `/dash/` shows the notebook's controls and outputs with no
`This section is unavailable.` placeholder.

## Troubleshoot

| Message or symptom                                                                              | Fix                                                                                                        |
| ----------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `Unknown view provider 'acme-views/vite'`                                                       | Install the package in the environment that runs Studio, check the entry point, and restart `marimo edit`. |
| `view.toml sets 'port', which Acme Vite does not read.`                                         | Add the option to `info.options`, or remove it from `view.toml`.                                           |
| `Provider working directory is outside the view snapshot`                                       | Run commands in `request.work_root` or `request.project.root`.                                             |
| `expected one element with id="app-shell"`                                                      | Keep one `#app-shell` element in the entry document.                                                       |
| `projection-site-missing`, and the page shows `This section is unavailable.` in place of a cell | Build from `request.project.root` and keep each host's `data-marimo-studio-site` attribute.                |

The [View provider API](../reference/provider-api.md) defines every record and
[each term](../reference/provider-api.md#terms) this page uses, including
projection sites, rendered documents, diagnostics, and provider options.
