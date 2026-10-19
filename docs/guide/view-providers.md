---
title: Add a view provider
description: Write a Python package that teaches Studio a new view format, from a frontend framework to a typesetting tool.
---

# Add a view provider

A [view provider](../reference/glossary.md#view-provider) is a Python package
that teaches Studio one [format](../reference/glossary.md#format). Install one
in the notebook's environment, and its starters appear in the **New view**
dialog beside the built-in ones:

![The New view dialog lists Acme report and Acme dashboard under acme-views, above the built-in starters from marimo-studio, and shows the files the selected Acme report creates](/screenshots/provider-new-view.png)

This page builds `acme-views`, the package in that dialog. **Acme report**
starts a plain HTML page and needs only Python. **Acme dashboard** adds a
[Lit](https://lit.dev/) component bundled by Vite.

::: warning Advanced feature
The view provider API is an advanced extension point. Pin `marimo-studio` to
the minor line you test, such as `marimo-studio>=0.4,<0.5`.
:::

## What a provider receives and returns

A provider works with the files of a
[view project](../reference/glossary.md#view-project). Studio calls its
methods at fixed moments and validates each record they return:

| When                                                 | Studio calls                   | The provider receives                                                                       | The provider returns                                                               |
| ---------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| The **New view** form opens                          | `availability()`, `starters()` | Nothing                                                                                     | Whether it can run, and its starters                                               |
| Someone creates a view                               | `create()`                     | The chosen starter and the saved notebook's cells                                           | The first files of the view project                                                |
| Source opens, or a file in the view project changes  | `inspect()`                    | The view project                                                                            | Its source documents, build inputs, hosts, and renders                             |
| Preview, `marimo run`, or an export needs a new page | `build()`                      | A [build snapshot](../reference/glossary.md#build-snapshot) of the build inputs             | A [page](../reference/glossary.md#page): an HTML entry file and the files it loads |
| A notebook result that a render reads changes        | `render()`                     | The render template, values as JSON, and outputs and cells as media, such as images or PDFs | [Rendered files](../reference/glossary.md#rendered-files), such as a PDF           |

A provider never runs the notebook. `build()` writes a page whose hosts are
still empty, and Studio fills them from the session while the page is open, as
[How Studio works](../how-studio-works.md#hosts-receive-results-while-the-page-is-open)
describes. `render()` is the one method that receives notebook results, and
they arrive already converted to JSON and images.

## Choose a pattern

Every provider imports one module, `marimo_studio.view_providers`. Pick the
pattern closest to your tool:

| Pattern                                                                | The build                                           | SDK pieces                                                  | Example                                                                                                                                            |
| ---------------------------------------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| [HTML page](#write-the-provider)                                       | copies or templates HTML                            | `html_sites`, `copy_inputs`                                 | this guide's `ReportProvider`                                                                                                                      |
| [Framework build](#add-a-framework-build)                              | bundles JavaScript with a pinned toolchain          | `request.runner`, `request.work_root`, `request.cache_root` | [`deno_react`](https://github.com/marimo-team/marimo-studio/tree/main/packages/marimo-studio/src/marimo_studio/view_providers/_builtin/deno_react) |
| [Command-line tool](../reference/provider-api.md#check-external-tools) | runs an installed tool that writes HTML             | `probe_tool`, `copy_inputs`, `ProviderError`                | [`quarto`](https://github.com/marimo-team/marimo-studio/tree/main/packages/marimo-studio/src/marimo_studio/view_providers/_builtin/quarto)         |
| [Rendered file](#publish-a-rendered-file)                              | renders files, such as a PDF, from notebook results | `Render`, `render_page`, `render()`                         | [`typst`](https://github.com/marimo-team/marimo-studio/tree/main/packages/marimo-studio/src/marimo_studio/view_providers/_builtin/typst)           |

When no pattern fits, start from the HTML page provider and replace `build()`
with your tool's steps. The built-in Quarto provider also imports private
`_builtin.quarto` helpers, so copy its use of the public module and keep
your provider's imports to `marimo_studio.view_providers`.

## Ask a coding agent

Open a coding agent in the notebook's project and paste this prompt:

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

For another framework, replace `Lit` with its name, and see
[Swap Lit for a JSX framework](#swap-lit-for-a-jsx-framework). The rest of the
page builds the same package by hand.

## Files in a view project

Pick **Acme report** and name the view `briefing`. Studio creates the view
project in the notebook's
[views folder](../reference/glossary.md#views-folder), `studio/analysis/` by
default:

```text
studio/analysis/briefing/
  view.toml    names the provider that owns this view
  index.html   the page, with one <marimo-cell> host per output cell
  AGENTS.md    instructions for coding agents that edit this view
```

The provider writes every file except `view.toml` and decides how Studio treats
it. A [source document](../reference/glossary.md#source-document) appears in
Studio's Source pane for editing. A
[build input](../reference/glossary.md#build-input) rebuilds the page when it
changes.

| File         | Written by                  | Source document     | Build input |
| ------------ | --------------------------- | ------------------- | ----------- |
| `index.html` | the provider, at creation   | yes                 | yes         |
| `AGENTS.md`  | the provider, at creation   | yes                 | no          |
| `DESIGN.md`  | the user or an agent, later | yes, once it exists | no          |
| `view.toml`  | Studio                      | yes                 | yes         |

`AGENTS.md` tells a coding agent which file holds the page, what the
`<marimo-cell>` hosts mean, and where decisions belong. The `marimo-studio`
agent skill reads it before editing a view, so ship one written for your
framework. `DESIGN.md` records lasting decisions such as audience, visual
direction, and interaction priorities once the view has a direction. Editing
either file never rebuilds the page.

## How Studio finds the provider

The package registers the provider in the `marimo_studio.view_provider`
[entry point group](https://packaging.python.org/en/latest/specifications/entry-points/),
the Python packaging mechanism that lets an installed package publish objects
to other packages. Studio derives these names from the registration:

| Name         | Value                            | Made from                               |
| ------------ | -------------------------------- | --------------------------------------- |
| Registration | `report = "acme_views:provider"` | Entry point in the `acme-views` package |
| Provider key | `acme-views/report`              | Distribution name and registration name |
| Starter ID   | `acme-views/report:default`      | Provider key and the starter key        |
| `view.toml`  | `provider = "acme-views/report"` | Written to the view project at creation |

Studio reads the entry points once per process, from its own Python
environment. Restart `marimo edit` after you install a provider or change its
starters. An unavailable provider's starters appear disabled with the recovery
action it returned.

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

Each method answers one moment from
[What a provider receives and returns](#what-a-provider-receives-and-returns).

### `availability()` and `starters()`: fill the New view dialog

`ReportProvider` needs only Python, so `availability()` always returns
`ProviderAvailability(True)`. A provider that runs an installed tool returns
`probe_tool(("tool", "--version"), minimum=..., install=...)`, which reports a
missing or outdated tool with your install instructions.

`starters()` returns one `ProviderStarter`. Its `title` names the starter in
the list, and `summary` and `documents` fill the starter's details. Add a
`format`, an SVG `icon`, a `preview` screenshot, a `homepage`, and `settings` to
present the starter the way the built-in ones are, as
[Present a starter in the New view dialog](../reference/provider-api.md#present-a-starter-in-the-new-view-dialog)
describes. Studio keeps the starter list for the life of the process.

### `create()`: write the starting files

`create()` runs once per new view. It receives the saved notebook in `context.notebook` and returns every file of the new project in a
`StarterPlan`. `ReportProvider` writes one `<marimo-cell>` host into
`index.html` for each cell in `context.output_cells`, and adds `AGENTS.md`.

`context.output_cells` lists the cells that may display output. It leaves out
disabled cells and their descendants, because marimo never runs them.

`context.cell_targets` supplies the name each host uses. A named cell such as
`summary` keeps its name. For an unnamed cell, Studio proposes an alias such as
`cell-2` and saves it in the notebook when the provider returns that target in
`StarterPlan.cell_targets`.

### `inspect()`: describe the project

`inspect()` returns a `ProjectInspection` with the project's documents, build
inputs, and projection sites. Studio also calls it before each build.

`documents` lists the Source documents, here `index.html`. Studio adds
`view.toml`, `AGENTS.md`, and `DESIGN.md` itself. `inputs` lists the build
inputs, so Studio rebuilds when `index.html` or `view.toml` changes. For a project with
many files, `project_files(request.project)` lists every file that can affect
a build.

`sites` holds one projection site per `<marimo-cell>`, `<marimo-output>`, or
`mo-value` host, the spot in the page that shows the result it names.
`html_sites()` records each host's line and column for Source diagnostics, and
reports a malformed host.

### `build()`: publish the page

`request.project.root` holds a snapshot of the build inputs, in which Studio
has already marked each site's host so it can connect the host to the
notebook. The `index.html` in Source keeps its original markup.
`ReportProvider` copies its inputs to `request.staging_root` with
`copy_inputs()`. Studio validates the staged files and publishes them as a new
revision. A failed build leaves the last good revision in Preview.

## Install it and create a view

From the notebook's project, install the package and check that Studio finds
it:

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

Start `uv run marimo edit analysis.py`, open the view menu, and choose **New
view**. **Acme report** appears under **From acme-views**, with **Files
created** listing `index.html, AGENTS.md`. Or create the view from the CLI:

```console
uv run marimo-studio view create briefing \
  --target analysis.py \
  --starter acme-views/report:default
```

Source shows one host per output cell in the page. Give the view a design
direction by saving `studio/analysis/briefing/DESIGN.md`:

```md
# Design

Audience: the weekly operations review.
Lead with the threshold control, then its result.
```

Studio lists `DESIGN.md` at its next inspection, such as after the next save of
`index.html`:

![Source pane for the briefing view with index.html, AGENTS.md, and DESIGN.md tabs, showing marimo-cell hosts named cell-2 and summary](/screenshots/provider-source.png){width=696}

Every environment that edits, builds, or exports the view needs the provider
package. Publish it to a package index, or declare it as a path or Git source
in the notebook's project.

## Add a framework build

**Acme dashboard** bundles a Lit component with [Vite](https://vite.dev/), a
frontend build tool that needs a JavaScript runtime. The machine that opens the
notebook may lack Node.js, so the provider uses [Deno](https://deno.com/), a
JavaScript runtime that also installs npm packages. The
[`deno`](https://pypi.org/project/deno/) package on PyPI installs it into the
same environment as Studio, and `deno.find_deno_bin()` returns its path.

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

The dashboard starter copies three files from `src/acme_views/dashboard/` into
every new view.

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

The lockfile records the version and checksum of every package in the
dependency tree. Rerun the command after you change `deno.json`.

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

- `availability()` checks for the `deno` binary, so the **New view** dialog
  shows the starter's recovery action and keeps **Create view** disabled when
  it is missing.
- `create()` copies `main.js`, `deno.json`, and `deno.lock` into the new view,
  and adds an `<acme-header>` element and a `<script>` tag to `index.html`.
- `inspect()` adds the three files to Source and to the build inputs.
  `deno.lock` opens read-only.
- `build()` copies the inputs to `request.work_root`, a private directory that
  Studio empties after the build. `deno install --frozen` installs the locked
  packages into `node_modules` and fails when `deno.json` and `deno.lock`
  disagree. Vite then bundles `main.js` into `request.staging_root` and keeps
  the site attributes on the hosts in `index.html`.

`DENO_DIR` keeps Deno's downloads in `request.cache_root`, which persists
between builds, so only the first build downloads Vite and Lit.
`request.runner.run()` stops a command when Studio cancels the build, and all
commands in one build share a 120-second budget. `check()` turns a nonzero exit
into a `ProviderError` that `marimo-studio view build` prints with the end of
the command's error output.

### Sandbox the build

npm packages run code inside Vite, so `build()` grants Vite only the
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
and `--frozen` limit it to the packages `deno install` placed. The
`package.json` and `pnpm-workspace.yaml` that `build()` writes stop Vite's
project root search from reading parent directories, and
`--configLoader=native` loads a `vite.config.js` without writing a temporary
file.

### Swap Lit for a JSX framework

To build the dashboard header with [Preact](https://preactjs.com/), change the
starter in four places:

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
  `node_modules`.
- Render components into their own element, such as `<div id="acme-header">`,
  and keep the `<marimo-cell>` hosts outside the component tree so the
  framework never replaces them.

To place hosts inside components, extend `inspect()` to report them as
`ProjectionSite` records from the component source, as the built-in providers
in
[`view_providers/_builtin`](https://github.com/marimo-team/marimo-studio/tree/main/packages/marimo-studio/src/marimo_studio/view_providers/_builtin)
do for JSX and Svelte.

## Publish a rendered file

A provider can declare a render: files it makes from one project file and
notebook results with its own tools. Its page shows the render with
`<marimo-output render="card.svg">`, named by that project file, and Studio
renders it again whenever a notebook result it reads changes. The host shows the main file, such as a PDF,
an image, or a video, with a download link.

Register `card = "acme_views.card:provider"`, then create
`src/acme_views/card.py`:

```python
from pathlib import PurePosixPath
from xml.sax.saxutils import escape

from marimo_studio.view_providers import (
    BuildInput,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    Rect,
    Render,
    RenderFile,
    RenderRegion,
    RenderRequest,
    RenderResult,
    RenderValue,
    SourceDocument,
    SourceLocation,
    StarterContext,
    StarterPlan,
    copy_inputs,
    render_page,
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
            renders=(
                Render(
                    CARD,
                    values=(RenderValue("report.total", SourceLocation(CARD, 2, 30)),),
                ),
            ),
        )

    def build(self, request: BuildRequest) -> BuildResult:
        copy_inputs(request, request.template_root)
        return BuildResult(render_page(request, CARD))

    def render(self, request: RenderRequest) -> RenderResult:
        template = (request.template_root / request.source).read_text("utf-8")
        total = request.values.get("report.total")
        text = "pending" if total is None else str(total)
        card = template.replace("{{ total }}", escape(text))
        (request.output_root / CARD).write_text(card, encoding="utf-8")
        # The total sits across the middle of the card, so Lens can select it.
        total_region = RenderRegion(
            CARD,
            Rect(x=0.05, y=0.35, width=0.7, height=0.35),
            reads=("report.total",),
            label="Report total",
        )
        return RenderResult(
            (RenderFile(CARD, "image/svg+xml"),), main=CARD, regions=(total_region,)
        )


provider = CardProvider()
```

`Render(CARD, values=...)` declares that the provider renders `card.svg` and
names the notebook values it reads, at the place it reads them. Each value arrives in its JSON form, so a
dataframe arrives as a list of row objects and a date as ISO 8601 text.

`build()` copies the declared build inputs into `request.template_root`, which
Studio keeps private, and writes a page with one `<marimo-output render="card.svg">` host
with `render_page()`. A provider that builds its own page places the host beside
its other content and hosts.

Studio calls `render()` with a writable copy of the template in
`request.template_root`, the file to render in `request.source`, an empty
`request.output_root`, and the reader's current results. A result without a
current value is absent and a null result is `None`, so the template shows
its default for both. `RenderResult` lists the files to publish with their
media types and names the main file. A render that places figures or named
cell outputs reads them with `RenderOutput` or `RenderCell`.
[Render files from notebook results](../reference/provider-api.md#render-files-from-notebook-results)
defines the contract, including figure sizes and preview files.

### Make parts of the file selectable

A rendered file is a picture of results, so Studio cannot tell on its own
which pixels show which result. `render()` returns a
[render region](../reference/glossary.md#render-region) for each part the
provider placed, and [Lens](lens.md) can select that part and trace it to its
cell. `CardProvider` returns one region, `total_region`, for the total across
the middle of the card.

`Rect` measures fractions of the file's width and height from its top left
corner. A PDF region also names its `page`, and a video region the `start` and
`end` seconds of the frames that show the part. Studio drops a region that
leaves its file or names no result the render reads, and warns once.
[Locate parts of rendered files](../reference/provider-api.md#locate-parts-of-rendered-files)
defines every field.

## Provider rules

Studio checks each result against these rules and reports the one it breaks.

- Implement every method as a synchronous function. Raise `ProviderError` for
  a problem the author can fix, and pass `source=` when it points at a file.
- Declare every provider option in `info.options`. Studio rejects a view whose
  `view.toml` sets any other option.
- List every file the build reads in `inputs`. The build snapshot holds only
  those files from the view project.
- Keep `inspect()` read-only. Put reusable data in `request.cache_root`.
- Report each host as a `ProjectionSite` whose `offset` points inside its start
  tag in the stored file. `html_sites()` does this for HTML. Match `kind` to the
  host: `cell` for `marimo-cell`, `output` for `marimo-output`, `value` for an
  element with `mo-value`.
- Build from the snapshot in `request.project.root` and keep the
  `data-marimo-studio-site` attribute on each host in the built files.
- Write the page inside `request.staging_root` and render templates inside
  `request.template_root`. The page needs one `head`, one `body`, and one
  element with `id="app-shell"`.
- Declare each render by its source file, a build input, and show only those
  files in `<marimo-output render="...">` hosts.
- Run `build()` commands with `cwd` inside `request.project.root`, which holds
  `request.work_root`, `request.staging_root`, and `request.template_root`. Run
  `render()` commands inside `request.template_root`.
- Pass `environment={**os.environ, ...}` to add variables. A mapping replaces
  the command's whole environment.
- Pin npm packages in a lockfile that ships with the starter, and install them
  with `deno install --frozen`.
- Run build tools that execute npm code with scoped Deno permissions, as in
  [Sandbox the build](#sandbox-the-build).
- Use a kebab-case diagnostic `code` and a non-empty `message` without leading
  or trailing whitespace.

Studio rebuilds a view when its inputs, the provider package version, or the
tool version from `availability()` change. Release a new version when the build
output changes for the same inputs.

## Verify the provider

Add `check_provider()` to the provider's tests. It runs each starter through
Studio's steps and raises `ProviderCheckError` with the message Studio would
show:

```python
from marimo_studio.view_providers.testing import check_provider

from acme_views import provider


def test_report_provider() -> None:
    (view,) = check_provider(provider)
    assert "index.html" in {path.as_posix() for path in view.published}
```

Pass the provider object while you develop it, or the installed key, such as
`check_provider("acme-views/report")`, to load it the way Studio does. Pass
`options={"entrypoint": "page.html"}` to check a provider option.
[`check_provider()`](../reference/provider-api.md#check-provider) lists every
check.

Then check the installed provider end to end from the notebook's project:

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
works when `/dash/` shows the notebook's controls and outputs and no
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
[term](../reference/provider-api.md#terms) on this page.
