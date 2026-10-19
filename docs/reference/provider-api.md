---
title: View provider API
description: Register a view provider that creates, inspects, builds, and renders view projects.
---

# View provider API

A [view provider](glossary.md#view-provider) connects a
[format](glossary.md#format) and its build command to Studio. It declares its
starters, the Source documents people edit, the build inputs that affect the
view, where the view shows notebook results, and how to build the page that
Studio publishes. A provider can also declare renders, which turn notebook
results into files such as a PDF or a video with the provider's own tools.

Studio owns notebook execution, Source writes, build snapshots, artifact
validation and publication, presentations, browser sessions, and agent
workflows. [Add a view provider](../guide/view-providers.md) builds and
installs a complete provider step by step.

::: warning View providers are trusted code
An installed provider runs Python and child commands with the current user's
filesystem permissions, environment variables, and network access. Studio runs
third-party calls in owned child processes to bound deadlines, output, and
cleanup. That process boundary contains the lifecycle and is not a security
sandbox. Review the provider package and its dependencies before installing it
in an environment that contains credentials or private notebook source.
:::

## Terms

The [glossary](glossary.md) defines each term. The API names it with these
records and fields:

| Term                                             | In the API                     |
| ------------------------------------------------ | ------------------------------ |
| [View project](glossary.md#view-project)         | `ViewProject`                  |
| [`view.toml`](glossary.md#view-toml)             | `ViewProject.manifest`         |
| [Provider key](glossary.md#provider-key)         | `ViewProject.provider`         |
| [Provider options](glossary.md#provider-options) | `ViewProject.options`          |
| [Starter](glossary.md#starter)                   | `ProviderStarter`              |
| [Starter key](glossary.md#starter-key)           | `ProviderStarter.key`          |
| [Starter ID](glossary.md#starter-id)             | `CheckedView.starter`          |
| [Cell target](glossary.md#cell-target)           | `StarterCellTarget`            |
| [Source document](glossary.md#source-document)   | `SourceDocument`               |
| [Build input](glossary.md#build-input)           | `BuildInput`                   |
| [Host](glossary.md#host)                         | Reported as a `ProjectionSite` |
| [Projection site](glossary.md#projection-site)   | `ProjectionSite`               |
| [Target](glossary.md#target)                     | `ProjectionSite.targets`       |
| [Build snapshot](glossary.md#build-snapshot)     | `BuildRequest.project`         |
| [Page](glossary.md#page)                         | `BuildResult.document`         |
| [Render](glossary.md#render)                     | `Render`                       |
| [Render template](glossary.md#render-template)   | `BuildRequest.template_root`   |
| [Render value](glossary.md#render-value)         | `RenderValue`                  |
| [Render output](glossary.md#render-output)       | `RenderOutput`                 |
| [Render cell](glossary.md#render-cell)           | `RenderCell`                   |
| [Rendered files](glossary.md#rendered-files)     | `RenderResult`                 |
| [Render region](glossary.md#render-region)       | `RenderRegion`                 |
| [Render host](glossary.md#render-host)           | Written by `render_page()`     |
| [Accept list](glossary.md#accept-list)           | `RenderOutput.accept`          |
| [Diagnostic](glossary.md#diagnostic)             | `ProjectDiagnostic`            |

## Register the provider

Publish one provider object through Python package metadata, and bind the
Studio dependency to the minor line the provider has tested:

```toml
[project]
name = "acme-views"
version = "0.1.0"
dependencies = ["marimo-studio>=0.4,<0.5"]

[project.entry-points."marimo_studio.view_provider"]
report = "acme_views:provider"
```

Studio derives the provider key from the canonical distribution name and the
entry point registration: distribution `acme-views` and registration `report`
produce `acme-views/report`. Moving a provider to another distribution changes
its key, so existing views must name the new key in `view.toml`.

One installed registration owns one provider key, and Studio rejects duplicate
registrations. A view stores its provider key in `view.toml`, and Source writes
preserve it. To switch a view to another provider, create a new view.

Test the provider against each Studio minor release before widening its
`marimo-studio` dependency. [Compatibility and support](compatibility.md) owns
the release policy.

## Implement the protocol

Publish an object that implements `ViewProvider`:

```python
class ViewProvider(Protocol):
    info: ProviderInfo

    def availability(self) -> ProviderAvailability: ...

    def starters(self) -> tuple[ProviderStarter, ...]: ...

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> StarterPlan: ...

    def inspect(self, request: InspectionRequest) -> ProjectInspection: ...

    def build(self, request: BuildRequest) -> BuildResult: ...
```

A provider that declares renders implements `RenderProvider`, which adds
`render()`, described in
[Render files from notebook results](#render-files-from-notebook-results).

```python
class RenderProvider(ViewProvider, Protocol):
    def render(self, request: RenderRequest) -> RenderResult: ...
```

Provider methods are synchronous. Studio runs them off the server event loop
and supplies a cancellation owner and a supervised command runner. Import
every name from `marimo_studio.view_providers`. Studio's other modules change
without notice.

`ProviderInfo` holds the title and summary shown in diagnostics, `options`,
the provider options the provider reads, and `requirement`, a short name for
what the provider needs to build, such as `"Quarto 1.9.38+"`. The **New view**
dialog shows "Needs Quarto 1.9.38+" beside each of its starters while the
provider is unavailable.

## Create starting files

`starters()` returns `ProviderStarter` records, each with a starter key, a
title and summary for the **New view** dialog, and `documents`, the Source
documents a new view starts with. Studio prefixes the starter key with the
provider key to form the starter ID: starter key `default` from
`acme-views/report` becomes `acme-views/report:default`.

`create()` returns a `StarterPlan`. `StarterPlan.files` holds every file the
provider writes and must include each path in `ProviderStarter.documents`.
Studio writes `view.toml` itself. Starter files cannot claim Studio paths such
as `view.toml`, `.artifacts/`, `.locks/`, or `.gitignore`. A starter may ship
`AGENTS.md` and `DESIGN.md` for coding agents, and Studio shows them in Source
when they exist.

`StarterContext.notebook` is a detached `NotebookSpec` for the saved notebook.
Its ordered cells include source, kind, name, literal Markdown, configuration,
definitions, references, and dependency edges. `create()` receives saved
notebook code, so install a provider only when its package is trusted with that
source.

`StarterContext.cell_targets` maps each ordinary cell to a `StarterCellTarget`:
the cell's marimo name, an existing Studio alias, or a new alias that Studio
proposes for an unnamed cell. `StarterContext.output_cells` returns, in
notebook order, the targets for cells that marimo runs and that may display
output. It skips disabled cells and cells downstream of a disabled cell.

Generated source uses `target.target` and returns the targets it used in
`StarterPlan.cell_targets`:

```python
import html
from pathlib import PurePosixPath

from marimo_studio.view_providers import StarterPlan

ENTRY = PurePosixPath("index.html")


def create(starter, context):
    selected = context.output_cells
    cells = "\n".join(
        f'<marimo-cell name="{html.escape(item.target, quote=True)}"></marimo-cell>'
        for item in selected
    )
    document = f'''<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>Notebook view</title></head>
  <body><main id="app-shell">{cells}</main></body>
</html>
'''
    return StarterPlan(
        files={ENTRY: document.encode()},
        cell_targets=selected,
    )
```

Studio validates `StarterPlan.cell_targets` against the context, then saves the
new aliases together with the project files. A notebook change or an alias
conflict before that commit rejects the whole creation. When saving aliases
changes notebook-local configuration, Studio calls `create()` again with the
notebook as it will be saved. Return the same `cell_targets` from both calls.

### Present a starter in the New view dialog

The dialog lists each starter with a mark and a short format, and shows the
selected starter's preview, summary, website, and documents:

```python
from importlib import resources
from pathlib import PurePosixPath

from marimo_studio.view_providers import ProviderStarter

STARTER = ProviderStarter(
    key="default",
    title="Report",
    summary="A paged report that lays out one notebook value.",
    documents=(PurePosixPath("main.typ"),),
    format="PDF",
    icon=resources.files(__name__).joinpath("icon.svg").read_text("utf-8"),
    preview=resources.files(__name__).joinpath("preview.webp").read_bytes(),
    homepage="https://acme.example/report",
)
```

| Field      | Contract                                                                                                      |
| ---------- | ------------------------------------------------------------------------------------------------------------- |
| `format`   | One line of at most 40 characters that names what the starter makes, such as `"Web app"`, `"Slides"`, `"PDF"` |
| `icon`     | SVG markup of at most 16 KiB with an `<svg>` root and no document type declaration                            |
| `preview`  | PNG, JPEG, or WebP bytes of at most 1 MiB, and 6 MiB across a provider's starters                             |
| `homepage` | An `https` URL for the technology the starter builds with                                                     |

Studio paints the icon's shapes as a mask in the theme's text color, so a
single-color square mark reads in light and dark themes. A starter without an
icon shows its preview, then its initial. Make the preview a 1280 by 800
screenshot of the view the starter creates. Studio serves it with an immutable
cache header keyed by its SHA-256 digest. A starter without a preview shows the
folder and documents it creates. Studio reads all four fields once per provider
and process, and carries them across the provider process boundary.

### Offer starter settings

`ProviderStarter.settings` lists values a person can change in the **New view**
dialog, with `marimo-studio view create --setting KEY=VALUE`, or with
`create_view(settings=...)` in code mode. Each `StarterSetting` has a key, a
label, help text the dialog shows beside the control, and a default:

```python
from marimo_studio.view_providers import SettingChoice, StarterSetting

SETTINGS = (
    StarterSetting(
        key="paper",
        label="Paper size",
        help="The page size of the PDF. main.typ sets it in its page rule.",
        default="a4",
        choices=(SettingChoice("a4", "A4"), SettingChoice("us-letter", "US Letter")),
    ),
    StarterSetting(
        key="toc",
        label="Table of contents",
        help="Lists the document's headings beside its text.",
        default=False,
    ),
)
```

A `bool` default makes a switch. `choices` make a choice whose default names one
of their values. Any other one-line `str` default makes a text field. Keys
match `[a-z][a-z0-9_]{0,63}`, and a starter declares at most 32 settings.

`create()` reads `StarterContext.settings`, which holds a value for every
declared setting: the person's choice or the default. Studio rejects an
undeclared key or a value that does not fit its setting before it calls
`create()`. `StarterContext.title` holds the title the starter writes into the view, which a
person can set in the dialog, with `--title`, or with `create_view(title=...)`.
Without one, Studio makes a title from the view name, so `quarterly-report`
becomes `Quarterly Report`.

### Ship starter files as package data

`PackagedStarter` keeps a starter's files in a package directory and fills
their `__MARKER__` markers when a view is created. Put the files in
`acme_views/starters/default/files/`, then return them from `create()`:

```python
import html
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    PackagedStarter,
    ProviderStarter,
    StarterContext,
    StarterMarkers,
    create_starter,
)


def markers(context: StarterContext) -> StarterMarkers:
    hosts = "\n".join(
        f'<marimo-cell name="{html.escape(item.target)}"></marimo-cell>'
        for item in context.output_cells
    )
    return StarterMarkers(
        values={"__CELLS__": hosts},
        cell_targets=context.output_cells,
    )


STARTERS = (
    PackagedStarter(
        ProviderStarter(
            key="default",
            title="Report",
            summary="Start from one HTML report.",
            documents=(PurePosixPath("index.html"),),
        ),
        package="acme_views.starters.default",
        markers=markers,
    ),
)


class ReportProvider:
    def starters(self):
        return tuple(starter.info for starter in STARTERS)

    def create(self, starter, context):
        return create_starter(STARTERS, starter, context)
```

`create_starter()` reads the files beneath `files/`, which needs no
`__init__.py`, and replaces each marker with its value. Every starter can also
use `__NOTEBOOK_LABEL_HTML__`, `__VIEW_TITLE_HTML__`,
`__NOTEBOOK_LABEL_JSON__`, and `__VIEW_TITLE_JSON__`, where the title is
`StarterContext.title`. The `_JSON` markers
produce a JSON string literal that is safe inside a `<script>` element, and
`script_json()` produces the same form for your own markers. Include the
`files/` directories in the package build so they ship in the wheel.

## Inspect the project

`inspect()` returns a `ProjectInspection`:

| Field         | Holds                                                         |
| ------------- | ------------------------------------------------------------- |
| `documents`   | The Source documents, in tab order                            |
| `inputs`      | The build inputs: exact files and bounded directories         |
| `sites`       | One projection site per host                                  |
| `diagnostics` | Problems found in the project                                 |
| `renders`     | The renders the view declares, each with the results it reads |

Studio watches the Source documents and the build inputs. The build inputs
also decide the project revision and the contents of the build snapshot.
Studio adds `view.toml` to the build inputs and lists `view.toml`, `AGENTS.md`,
and `DESIGN.md` in Source. Leave a Source document out of the build inputs
when editing it should skip a rebuild.

For a project whose build inputs follow its directory layout,
`project_files(project, roots=..., exclude=...)` lists the files a build can
read.

`inspect()` must leave the project unchanged. Keep downloaded or generated data
beneath `request.cache_root`.

### Read provider options

`request.project.options` holds the `[options]` table of `view.toml`:

```toml
schema = 1
provider = "acme-views/report"

[options]
entrypoint = "pages/index.html"
```

Declare each option in `ProviderInfo.options`. Studio reports
`provider-options-invalid` for any other option before it calls the provider.
`ViewProject.path_option()` reads a project-relative path:

```python
info = ProviderInfo(
    title="Acme report",
    summary="Publishes one HTML report.",
    options=frozenset({"entrypoint"}),
)


def inspect(self, request):
    entry = request.project.path_option(
        "entrypoint", default="index.html", suffix=".html"
    )
```

An invalid value raises `ProviderError` located at `view.toml`, which Studio
shows as a diagnostic.

### Report projection sites

`html_sites()` finds the projection site of every host in an HTML document:

```python
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    BuildInput,
    ProjectInspection,
    SourceDocument,
    html_sites,
)

ENTRY = PurePosixPath("index.html")


def inspect(self, request):
    source = (request.project.root / ENTRY).read_bytes()
    sites, diagnostics = html_sites(ENTRY, source)
    return ProjectInspection(
        documents=(SourceDocument(ENTRY, "html", "edit"),),
        inputs=(BuildInput(ENTRY, "file"),),
        sites=sites,
        diagnostics=diagnostics,
    )
```

For an `index.html` that contains this line:

```html
<marimo-cell name="summary"></marimo-cell>
```

`html_sites()` returns one site:

```text
ProjectionSite(
    kind="cell",
    targets=("summary",),
    source=SourceLocation(PurePosixPath("index.html"), line=1, column=1),
    offset=27,
)
```

Before Studio calls `build()`, it derives a stable site ID and inserts it at
`offset` in the build snapshot. The provider builds the snapshot files as they
are, so the built page contains:

```html
<marimo-cell name="summary" data-marimo-studio-site="site-…"></marimo-cell>
```

Keep each host and its `data-marimo-studio-site` attribute in the built output.
A build that drops a host publishes with a `projection-site-missing` warning,
and that host shows no notebook result. Studio reserves
`data-marimo-studio-site`, and `html_sites()` reports `projection-site-reserved`
when authored source contains it.

A provider for another source format reports the same records from its own
parser:

| Field     | Contract                                                                                                          |
| --------- | ----------------------------------------------------------------------------------------------------------------- |
| `kind`    | `cell` for `marimo-cell`, `output` for `marimo-output`, and `value` for an element with `mo-value`                |
| `targets` | The targets the host may show, or `"*"` for a host with `data-marimo-allow="*"` whose page script sets its target |
| `source`  | One-based line and column of the host in a Source document                                                        |
| `offset`  | UTF-8 byte offset inside the host start tag, usually just before `>`, in the file as stored                       |
| `accept`  | The image types an output host lists in its `accept` attribute, read with `parse_accept()`                        |

The file that contains a site must be a build input, and each offset must be
unique within its file. The byte at `offset` must be whitespace, `/`, or `>`
inside the host's start tag.

## Build browser files

`BuildRequest` holds the build snapshot as `request.project`, its inspection,
the build input paths, the project revision, the build profile, four working
directories, a cancellation owner, a command budget, and a supervised runner.

Write the output beneath `request.staging_root` and return the entry document
in `BuildResult`. A build that copies its sources is two lines:

```python
def build(self, request):
    copy_inputs(request, request.staging_root)
    return BuildResult(ENTRY)
```

Run frontend tools in `request.work_root`, an empty directory Studio deletes
after the build, and copy their output to `request.staging_root`:

```python
def build(self, request):
    work = request.work_root.resolve()
    copy_inputs(request, work)
    result = request.runner.run(["deno", "task", "build"], cwd=work)
    if result.returncode != 0:
        raise ProviderError(
            f"deno task build failed: {result.stderr.strip()[-2000:]}",
            hint="Fix the error in the view's source, then build again.",
        )
    shutil.copytree(work / "dist", request.staging_root, dirs_exist_ok=True)
    return BuildResult(ENTRY)
```

`BuildResult.document` names the page, an `.html` file beneath
`request.staging_root`. The `development` profile builds Studio Preview, and
the `production` profile builds run mode and static export. Each profile keeps
its own build state and publication.

An HTML entry document needs one `head`, one `body`, and one `#app-shell`.
Studio validates paths, symlinks, file limits, reserved routes, projection
sites, render hosts, and the complete output before publication.

## Render files from notebook results

A render turns notebook results into files with the provider's tools: a PDF
compiled from Typst, a video encoded from a scene, or a Word document filled
from a template. A render is named by the project file it starts from, and the
page shows it with a render host for that file:

```html
<marimo-output render="main.typ"></marimo-output>
```

Studio runs the render for each reader whenever a result it reads changes,
and the host shows the new files when they are ready.
[Rendered files](projections.md#rendered-files) describes the host. The
built-in Typst and LaTeX providers render their entry document, such as
`main.typ`.
[Publish a rendered file](../guide/view-providers.md#publish-a-rendered-file)
builds a provider step by step.

1. `inspect()` declares each render as a `Render` with its source file, a
   build input such as `main.typ`, and the results it reads: each value it
   reads as JSON as a `RenderValue`, each value it places, such as a figure,
   as a `RenderOutput`, and each named cell whose output it places as a
   `RenderCell`. Each read carries its target and source location, and media
   reads carry the types the render can place.
2. `build()` writes the page beneath `request.staging_root` and the files
   renders start from beneath `request.template_root`, such as a copy of the
   project. Studio stores the template privately with the artifact. A build
   that compiles the template can measure where it places each output and
   return those sizes in `BuildResult.output_sizes`.
3. While the view runs, Studio captures the results a render reads from the
   reader's notebook, calls `render()` with the render's source and a
   writable copy of the template, and publishes the files it returns. A
   static export calls it once for each distinct prepared state.

Studio publishes the template a build returns, and readers render from it.
Fail the build when a render source cannot render with absent results, so a
broken source keeps the last published view. The built-in Typst and LaTeX
providers compile each render source during the build.

`render()` must depend only on the template and the request's `values`,
`outputs`, and `cells`. Studio stores the files of each render by artifact
revision and inputs and shares them among readers with the same results.
Studio may run two renders of one view at once, each with its own template
copy and output directory. Treat the request's results as untrusted data from
the notebook a reader is viewing.

When the results a render reads change while it runs, Studio renders the new
results and stops the outdated render a few seconds later, unless a reader asks
for the same results again first. Studio ends an installed provider's process.
A provider running in Studio's process, such as one passed to
`check_provider()`, stops at its next `request.runner` command or
`request.cancellation` check.

Return every file the reader receives in `RenderResult.files`, each with its
media type, and name the file a reader opens and downloads in `main`. Name a
companion that a page shows in its place, such as a video's poster image or a
PDF of a Word document, in `preview`. Studio keeps the files' relative paths,
so an HTML file loads its images and stylesheets.

A source renders once for each set of notebook results, so one render returns
every form of it that the view shows. A Typst render can return the report as
`report.pdf`, a first-page thumbnail as `thumbnail.png`, and a slide image as
`slides/cover.png`. The stock host shows the main file, and a page that places
another form reads its URL from the host's
[render record](projections.md#render-records). When the template cannot
render with the supplied results, raise `ProviderError` or return error
diagnostics, and the page keeps showing the last rendered files with the
diagnostics beside them.

Render values hold the
[JSON form](../guide/notebook-results.md#renders-read-json) of each notebook
value: a dataframe arrives as a list of row objects, a date as ISO 8601 text,
and a step through `None` as `null`. A target without a current result is
absent. Give `null` the same default as an absent target.

Each render reads its targets on its own, so a page host and a render, or two
renders, can read one figure in different media types and sizes. Studio
captures a render's reads between two notebook runs in every runtime, so one
render never mixes results from different runs.

### Locate parts of rendered files

Return `RenderResult.regions` to tell Studio which part of a rendered file
each notebook result produced. A `RenderRegion` is a rectangle on one surface
of a file: a PDF page, an image, or a video's frames between two times. The
page shows each region over the file as a
[selection target](projections.md#select-parts-of-rendered-files), so a reader
can point at a chart inside a PDF, or at a shape in one frame of a video, and
follow it to the cells that computed it:

```python
from pathlib import PurePosixPath

from marimo_studio.view_providers import Rect, RenderFile, RenderRegion, RenderResult

RenderResult(
    files=(RenderFile(PurePosixPath("report.pdf"), "application/pdf"),),
    main=PurePosixPath("report.pdf"),
    regions=(
        RenderRegion(
            PurePosixPath("report.pdf"),
            Rect(x=0.12, y=0.2, width=0.76, height=0.3),
            reads=("revenue_chart",),
            page=1,
            label="Revenue chart",
        ),
        RenderRegion(
            PurePosixPath("report.pdf"),
            Rect(x=0.12, y=0.55, width=0.1, height=0.02),
            reads=("rows[3].total",),
            page=1,
        ),
    ),
)
```

`Rect` holds fractions of the surface's width and height, measured from its
top left corner. The other fields are keyword arguments:

| Field             | Meaning                                                                                                 | Default                                               |
| ----------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `reads`           | Targets the part shows, as declared in `inspect()`, optionally narrowed by `.field` and `[index]` steps | Required, at least one                                |
| `page`            | The PDF page, counted from 1. Required for a PDF                                                        | `None`                                                |
| `start` and `end` | The seconds of a video during which the part shows                                                      | The whole video                                       |
| `source`          | Where the render's source places the part, shown as the selection's rendering source                    | The source line where the render reads its first read |
| `label`           | The name Lens shows for the selection                                                                   | The first read                                        |

A read such as `rows[3].total` names one cell of the `rows` table. Studio
resolves each read through the render's read site to the cell that produced
it. A video region names the frames a shape appears in:

```python
RenderRegion(
    PurePosixPath("scene.mp4"),
    Rect(x=0.4, y=0.3, width=0.2, height=0.25),
    reads=("kernel",),
    start=1.5,
    end=4.0,
)
```

Regions are evidence beside the files, and the files publish whatever the
regions hold. Studio leaves out a region whose file the render did not publish,
whose rectangle leaves its surface, or that names no result the render reads.
It removes each read that names a result the render does not read and keeps
the region. One `render-regions-invalid` warning reports both. A region that
is not a `RenderRegion` with a `Rect` fails provider conformance, as any
malformed record does. A render
keeps its first 4,096 regions and warns with `render-regions-limited` about
the rest. Each region keeps its first 64 reads, and Studio shortens a label to
256 characters. The built-in Typst and LaTeX providers return a region for
each placed output and cell, and for each part the document marks with
`marimo_region()` or `\marimoregion`.

## Report problems

Raise `ProviderError` from `inspect()`, `build()`, or `render()` when the
author can fix the problem in the project:

```python
raise ProviderError(
    "main.typ imports missing.typ.",
    hint="Create missing.typ or remove the import.",
    source=SourceLocation(PurePosixPath("main.typ"), 3, 1),
)
```

`hint` names the author's next step. Put tool output, such as a compiler's
error text, in the message. Studio strips surrounding whitespace from both,
shows them beside `source` in Source, and keeps the last published view. When
`inspect()` raises, Studio opens the `source` file in Source for repair. When a
build error's `source` names a file outside Source, Studio puts that location
at the start of the message.

Return diagnostics in `ProjectInspection.diagnostics`,
`BuildResult.diagnostics`, or `RenderResult.diagnostics` to report several
problems at once, or a warning that still publishes. Studio reports any other exception as a provider failure with
the provider key.

## Run commands

`request.runner.run(command, cwd=...)` starts a supervised child command. In
`inspect()` and `build()`, `cwd` must be inside `request.project.root`, which
holds `request.work_root`, `request.staging_root`, and `request.template_root`.
In `render()`, it must be inside `request.template_root`.

- `timeout` is a finite positive number of seconds, 120 by default. Every
  command in one request also shares `request.command_timeout` as a total
  budget.
- `environment=None` inherits the Studio process environment. A mapping
  replaces the whole environment, so pass `environment={**os.environ, ...}` to
  add variables.

The runner raises `ProviderCommandError` when a command exceeds its budget or
output limit, or when the operation is cancelled. Let it propagate.

`request.cancellation.raise_if_cancelled(action)` stops long filesystem work
that the runner does not own. A callback registered with
`request.cancellation.register()` can interrupt a long library call. Call the
returned function to unregister it when the call completes. Both take effect
when the provider runs in Studio's process, as a built-in provider or a
provider object passed to `check_provider()` does.

Studio runs installed providers in an owned child process. Cancellation, a
deadline, or excessive command output can end that process before the provider
runs cleanup code. Keep temporary files beneath `request.staging_root` and
`request.work_root`, keep reusable state beneath `request.cache_root`, and
leave publication to Studio.

## Check external tools

`availability()` reports whether the provider can run. `probe_tool()` runs a
tool's version command and compares the first dotted version it prints:

```python
def availability(self):
    return probe_tool(
        ["typst", "--version"],
        minimum="0.13",
        install="Install Typst 0.13 or newer from https://typst.app.",
    )
```

Studio shows `reason` and `action` in the **New view** form and in
`marimo-studio doctor`. Studio records the `availability()` version with each
build, so a tool upgrade rebuilds the views that use the provider.

`find_tool()` returns the path of the executable a command name runs. It
searches `PATH`. A provider call for a standalone notebook with a
`[tool.pixi]` table in its `# /// script` metadata searches the executable
directories of the notebook's [pixi](https://pixi.prefix.dev/) script
environment first, while marimo runs the notebook with `--sandbox=pixi` or a
`marimo-studio` command targets it. `probe_tool()` finds and runs its command
the same way. `request.runner` puts those directories first on `PATH` for a
command that inherits Studio's environment, and an `environment` mapping
replaces the whole environment. A command that passes its own `environment`
runs the path `find_tool()` returns:

```python
typst = find_tool("typst")
if typst is None:
    raise ProviderError("Studio cannot find the typst command.")
request.runner.run(
    [typst, "compile", "main.typ", str(request.work_root / "main.pdf")],
    cwd=request.project.root,
    environment={**os.environ, "SOURCE_DATE_EPOCH": "0"},
)
```

## Record reference

### Provider records

```text
ProviderInfo(
    title: str,
    summary: str,
    options: frozenset[str] = frozenset(),
    requirement: str | None = None,
)

ProviderAvailability(
    available: bool,
    version: str | None = None,
    reason: str | None = None,
    action: str | None = None,
)

ProviderStarter(
    key: str,
    title: str,
    summary: str,
    documents: tuple[PurePosixPath, ...],
    *,
    format: str | None = None,
    icon: str | None = None,
    preview: bytes | None = None,
    homepage: str | None = None,
    settings: tuple[StarterSetting, ...] = (),
)

StarterSetting(
    key: str,
    label: str,
    help: str,
    default: str | bool,
    choices: tuple[SettingChoice, ...] = (),
)

SettingChoice(value: str, label: str)
```

Studio validates `ProviderInfo` when it discovers the provider. Return `reason`
and an actionable `action` when `available` is false.

### `ViewProject`

```text
ViewProject(
    name: str,
    root: Path,
    manifest: Path,
    provider: str,
    options: Mapping[str, JsonValue],
)

project.path_option(name: str, *, default: str, suffix: str | None = None) -> PurePosixPath
```

`manifest` is the path of `view.toml`, `provider` is the provider key, and
`options` holds the provider options as detached JSON-compatible data.
`path_option()` returns option `name`, or `default`, as a project-relative
path. It raises `ProviderError` at `view.toml` when the value leaves the
project or lacks `suffix`, compared without case.

### Starter records

```text
StarterContext(
    view_name: str,
    notebook_name: str,
    notebook: NotebookSpec,
    cell_targets: Mapping[CellRef, StarterCellTarget],
    *,
    title: str,
    settings: Mapping[str, str | bool] = {},
)

StarterCellTarget(cell: CellRef, target: str)

StarterPlan(
    files: Mapping[PurePosixPath, bytes],
    cell_targets: tuple[StarterCellTarget, ...],
)

PackagedStarter(
    info: ProviderStarter,
    package: str,
    markers: Callable[[StarterContext], StarterMarkers] = ...,
)

StarterMarkers(
    values: Mapping[str, str] = {},
    cell_targets: tuple[StarterCellTarget, ...] = (),
)

create_starter(
    starters: Sequence[PackagedStarter],
    requested: ProviderStarter,
    context: StarterContext,
) -> StarterPlan

script_json(value: str) -> str
```

`StarterContext.app_title` returns the notebook's configured app title or
`None`, and `notebook_label` returns the app title or a readable form of the
notebook filename. [Create starting files](#create-starting-files) describes
`output_cells`.

`create_starter()` reads the files in `<package>/files`, replaces each marker
with its value from `StarterMarkers.values`, and returns the plan with
`StarterMarkers.cell_targets`. Marker names match `__[A-Z0-9_]+__`. It raises
`ValueError` for an unknown starter or for a `ProviderStarter.documents` path
missing from the files. `script_json()` returns a JSON string literal that
cannot close a `<script>` element.

### Inspection records

```text
ProjectInspection(
    documents: tuple[SourceDocument, ...],
    inputs: tuple[BuildInput, ...],
    sites: tuple[ProjectionSite, ...] = (),
    diagnostics: tuple[ProjectDiagnostic, ...] = (),
    renders: tuple[Render, ...] = (),
)

SourceDocument(
    path: PurePosixPath,
    language: str,
    access: DocumentAccess,
    label: str | None = None,
)

BuildInput(path: PurePosixPath, kind: BuildInputKind)

ProjectionSite(
    kind: ProjectionKind,
    targets: tuple[str, ...] | Literal["*"],
    source: SourceLocation,
    offset: int,
    accept: tuple[str, ...] = (),
)

Render(
    source: PurePosixPath,
    values: tuple[RenderValue, ...] = (),
    outputs: tuple[RenderOutput, ...] = (),
    cells: tuple[RenderCell, ...] = (),
)

RenderValue(target: str, source: SourceLocation)

RenderOutput(target: str, source: SourceLocation, accept: tuple[str, ...])

RenderCell(target: str, source: SourceLocation, accept: tuple[str, ...])

SourceLocation(path: PurePosixPath, line: int, column: int)
```

`SourceDocument.path` is a contained, project-relative POSIX path, `language`
is the editor language ID, and `label` is an optional tab name. A directory
`BuildInput` covers every file beneath it, within Studio's input limits.
`ProjectionSite.targets` must be non-empty and unique, and `"*"` permits any
valid target of `kind`. `Render.source` is a project-relative POSIX path
covered by the build inputs, such as `main.typ`, and a view declares each
source once. A `RenderCell` target is a cell name. Several reads
of one kind in a render may share a target. `SourceLocation` lines and columns
are one-based.

`accept` lists lowercase `type/subtype` media types in order of preference,
such as `("application/pdf", "image/svg+xml", "image/png")`. An output site, a
`RenderOutput`, and a `RenderCell` take one. Studio passes a cell's output as
marimo shows it, in the first listed type the output carries, and renders an
output's value in the first type the value supports through marimo-export's
[`represent()`](https://marimo-team.github.io/marimo-export/reference/python/values),
whatever output settings the notebook uses. An output site without `accept`
shows marimo's native output. An output site lists image types a page shows:
`image/svg+xml`, `image/png`, `image/jpeg`, or `image/gif`. A `"*"` output site
declares no `accept` and shows each target in the form its literal sites
declare. Every page host of one output target uses the same accept list, and
every read of one output or cell target in one render does too. A different
list reports `output-accept-conflict`. A render and a page host may read one
target in different forms.

Each artifact revision records the provider distribution's version and the
`availability()` version, so an upgrade never reuses output built by the
earlier version.

### Diagnostics

```text
ProjectDiagnostic(
    code: str,
    severity: Literal["warning", "error"],
    message: str,
    hint: str = "",
    source: SourceLocation | None = None,
)

ProviderError(
    message: str,
    *,
    hint: str = "",
    source: SourceLocation | None = None,
    code: str = "provider-error",
)
```

An error diagnostic blocks publication. Use a kebab-case `code` and a
non-empty `message`, and add `source` and `hint` when a Source edit can repair
the problem. `ProviderError.diagnostic` holds the error diagnostic Studio
shows.

### Requests and results

```text
InspectionRequest(
    project: ViewProject,
    runner: ProviderRunner,
    cancellation: ProviderCancellation,
    cache_root: Path,
    command_timeout: float,
)

BuildRequest(
    project: ViewProject,
    inspection: ProjectInspection,
    inputs: tuple[PurePosixPath, ...],
    project_revision: str,
    profile: BuildProfile,
    staging_root: Path,
    template_root: Path,
    work_root: Path,
    cache_root: Path,
    cancellation: ProviderCancellation,
    runner: ProviderRunner,
    command_timeout: float,
)

BuildResult(
    document: PurePosixPath | None,
    diagnostics: tuple[ProjectDiagnostic, ...] = (),
    output_sizes: Mapping[PurePosixPath, Mapping[str, Size]] = {},
)

Size(width: float | None = None, height: float | None = None)

RenderRequest(
    source: PurePosixPath,
    template_root: Path,
    values: Mapping[str, JsonValue],
    outputs: Mapping[str, Representation],
    cells: Mapping[str, Representation],
    output_root: Path,
    cancellation: ProviderCancellation,
    runner: ProviderRunner,
    command_timeout: float,
)

RenderResult(
    files: tuple[RenderFile, ...] = (),
    main: PurePosixPath | None = None,
    preview: PurePosixPath | None = None,
    diagnostics: tuple[ProjectDiagnostic, ...] = (),
    regions: tuple[RenderRegion, ...] = (),
)

RenderFile(path: PurePosixPath, media_type: str)

RenderRegion(
    file: PurePosixPath,
    rect: Rect,
    *,
    reads: tuple[str, ...],
    page: int | None = None,
    start: float | None = None,
    end: float | None = None,
    source: SourceLocation | None = None,
    label: str | None = None,
)

Rect(x: float, y: float, width: float, height: float)
```

`BuildRequest.inputs` lists every build input file, with directories expanded.
`staging_root` receives the page and its assets, `template_root` receives the
private files renders start from, `work_root` is an empty directory for
intermediate files, and `cache_root` persists between builds. Return
`document=None` when diagnostics prevent publication.

`BuildResult.output_sizes` maps a render's source, then an output target the
render reads, to the
[`Size`](https://marimo-team.github.io/marimo-export/reference/python/values#size),
in points, at which the template places it: its width, its height, or both. A
size with only a height keeps the figure's aspect ratio, as an image placed by
height does. Studio then draws a matplotlib figure or a Vega-Lite chart
at that size for every render, so its text keeps the point size the notebook
set. A target without a size arrives at the size the notebook drew it. A size
for a target the render does not read fails provider conformance. The LaTeX
provider reads the sizes `marimo.sty` logs during the build compile, and the
Typst provider queries the records `marimo_output()` places.

`RenderRequest.source` is the `Render.source` to render, and `template_root`
is a private, writable copy of everything `build()` wrote beneath
`BuildRequest.template_root`, so a build that copies the project there finds
the source at `template_root / source`. A build writes anything else its
renders need into the template, such as settings read from provider options or
from `BuildRequest.profile`, so every render of one artifact sees the same
inputs. `values` holds the JSON form of each available `RenderValue` target.
`outputs` and `cells` hold a marimo-export
[`Representation`](https://marimo-team.github.io/marimo-export/reference/python/values#representation)
for each available `RenderOutput` and `RenderCell` target, in one of the media
types its `accept` lists, such as
`Representation("application/pdf", b"%PDF-...")`. Text media types hold UTF-8
bytes. A PNG figure also carries its display `width` and `height` in CSS
pixels. A target without a current result, or whose result has no accepted
media type, is absent, and the template shows its default. Write files the
renderer reads, such as images, into `template_root`. `output_root` starts
empty.

`RenderResult.files` lists every file beneath `output_root` that Studio
publishes, each with a lowercase `type/subtype` media type such as
`"video/mp4"`. Files left out of the list stay private to the render. `main`
and `preview` name listed files, and `preview` differs from `main`. Return no
`main`, with an error diagnostic, when the render fails. Warning diagnostics
publish with the files.

`RenderResult.regions` locates parts of the published files. A region's
`file` names a listed PDF, `image/*`, or `video/*` file. A PDF region names
its `page`, counted from 1. A video region shows from `start` until `end`
seconds, from the first frame when `start` is `None`, and until the video ends
when `end` is `None`. `Rect` coordinates are fractions from 0 to 1 of the
surface's width and height, from its top left corner. A region without a
`source` takes the source of the read site of its first read, and a region
without a `label` shows its first read. Studio keeps the first 64 reads of a
region and the first 4,096 regions of a render.

### Commands and cancellation

```text
runner.run(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float = 120.0,
    environment: Mapping[str, str] | None = None,
) -> ProviderCommandResult

cancellation.cancelled -> bool
cancellation.raise_if_cancelled(action: str = "The provider operation") -> None
cancellation.register(callback: Callable[[], None]) -> Callable[[], None]
```

`request.runner` is a `ProviderRunner`, and `request.cancellation` is a
`ProviderCancellation`. `ProviderCommandResult` holds `returncode`, bounded
`stdout`, and bounded `stderr`. `raise_if_cancelled()` also raises
`ProviderCommandError`.

### Type aliases

| Name             | Type                                                                                  |
| ---------------- | ------------------------------------------------------------------------------------- |
| `BuildProfile`   | `Literal["development", "production"]`                                                |
| `BuildInputKind` | `Literal["file", "directory"]`                                                        |
| `DocumentAccess` | `Literal["edit", "read"]`                                                             |
| `ProjectionKind` | `Literal["cell", "output", "value"]`                                                  |
| `CellKind`       | `Literal["cell", "setup", "function", "class", "unparsable"]`                         |
| `JsonValue`      | A JSON-compatible scalar, list, or string-keyed dictionary, such as a provider option |

### Helpers

```text
project_files(
    project: ViewProject,
    *,
    roots: Collection[str] | None = None,
    exclude: Collection[str] = (),
) -> tuple[PurePosixPath, ...]

copy_inputs(
    request: BuildRequest,
    destination: Path,
    *,
    include: Callable[[PurePosixPath], bool] | None = None,
) -> None

render_page(request: BuildRequest, source: PurePosixPath, *, title: str | None = None) -> PurePosixPath

project_path(value: object, *, field: str = "Project path") -> PurePosixPath

html_sites(
    path: PurePosixPath,
    source: bytes,
) -> tuple[tuple[ProjectionSite, ...], tuple[ProjectDiagnostic, ...]]

parse_accept(kind: ProjectionKind, text: str | None) -> tuple[str, ...]

find_tool(command: str) -> str | None

probe_tool(
    command: Sequence[str],
    *,
    minimum: str,
    install: str,
    environment: Mapping[str, str] | None = None,
) -> ProviderAvailability
```

`project_files()` returns the sorted regular files under `project.root`.
`roots` keeps only these top-level entries, and `exclude` skips top-level
directories by name. It skips hidden top-level entries, such as `.env`, and
the files Studio owns, such as `view.toml`, `AGENTS.md`, and `DESIGN.md`. It
raises
`ProviderError` for a symlink or a project over the
[input limits](limits.md#provider-records).

`copy_inputs()` copies each path in `request.inputs` except `view.toml` to the
same relative path beneath `destination`. `include` selects the paths to copy,
so a build that serves a page beside a render copies page files and `public/`
assets into `request.staging_root` and render sources into
`request.template_root`:

```python
def page(path):
    return path.parts[0] == "public" or path.suffix in {".html", ".css", ".js"}


copy_inputs(request, request.staging_root, include=page)
copy_inputs(request, request.template_root, include=lambda path: not page(path))
```

`render_page()` writes `index.html` beneath `request.staging_root` with one
render host for `source` that fills the view, and returns
`PurePosixPath("index.html")`. `title` sets the page title and defaults to the
view's name. A provider whose view shows one rendered document returns this
page from `build()`:

```python
def build(self, request):
    copy_inputs(request, request.template_root)
    return BuildResult(render_page(request, PurePosixPath("card.svg")))
```

`project_path()` normalizes a project-relative POSIX path. It raises
`ValueError` for absolute paths, `..` segments, backslashes, and names that are
not portable across operating systems.

`html_sites()` parses `source` as HTML and returns its projection sites with
diagnostics for invalid hosts. A render host is part of the page and has no
projection site, and an invalid render host, such as one that also sets
`value`, reports a diagnostic. `source` holds the file bytes as stored, so each
`offset` points into the same bytes Studio marks. When the markup cannot be
parsed, the result keeps the sites found before the parse error.

`parse_accept()` reads a host's `accept` attribute text, such as
`"image/svg+xml, image/png"`, into lowercase media types in preference order.
`None`, for a host without the attribute, returns an empty tuple. Spaces or
commas separate the types, and each must be `image/svg+xml`, `image/png`,
`image/jpeg`, or `image/gif`. It raises `ValueError` for an `accept` on a cell
or value host, an empty list, a malformed or repeated type, or another media
type. Report the message as a `projection-accept-invalid` diagnostic at the
host, and keep reporting the file's other hosts.

`probe_tool()` finds `command[0]` on `PATH` unless it is a path, runs it with a
30 second deadline, and compares the first dotted version in its output with
`minimum`. It reads standard error when standard output has none, and a
prerelease such as `2.9.5-rc.1` compares below its release. An unavailable
result carries a `reason`, such as a timeout, an exit status, or an old
version, and `install` as its `action`. The process remembers a reported
version until the executable changes, and checks again after a failed or
cancelled check. It raises `ProviderCommandError` when the operation is
cancelled.

### `check_provider()`

```text
from marimo_studio.view_providers.testing import check_provider

check_provider(
    provider: ViewProvider | str,
    *,
    key: str = "local-provider/provider",
    notebook: str | Path | None = None,
    values: Mapping[str, JsonValue] | None = None,
    outputs: Mapping[str, Representation] | None = None,
    cells: Mapping[str, Representation] | None = None,
    options: Mapping[str, JsonValue] | None = None,
) -> tuple[CheckedView, ...]

CheckedView(
    starter: str,
    documents: tuple[PurePosixPath, ...],
    published: Mapping[PurePosixPath, bytes],
    warnings: tuple[str, ...],
    renders: Mapping[PurePosixPath, CheckedRender] = {},
)

CheckedRender(
    main: PurePosixPath,
    preview: PurePosixPath | None,
    files: Mapping[PurePosixPath, bytes],
    media_types: Mapping[PurePosixPath, str],
    regions: tuple[RenderRegion, ...] = (),
    warnings: tuple[str, ...] = (),
)
```

`check_provider()` runs each starter through the same steps as Studio. It
creates a view next to a sample notebook, inspects it twice, builds and
publishes it, and runs every render the view declares:

```python
from marimo_studio.view_providers.testing import check_provider

from acme_views import provider


def test_report_provider() -> None:
    (view,) = check_provider(provider)
    assert "index.html" in {path.as_posix() for path in view.published}
```

`provider` is a provider object, checked in process under `key`, or an
installed provider key, loaded the way Studio loads it. `notebook` defaults to
a notebook that defines `metric` and `report`. `options` become the provider
options of each view. `values`, `outputs`, and `cells` feed
each declared render for the targets it reads, as Studio supplies them, and
`renders` holds the files each render returned, by render source, with the
regions Studio kept and the render's warnings. Each output
and cell is a `Representation` in one of the media types the render accepts.
`CheckedView.starter` is the starter ID, `documents` lists the view's Source
documents, and `warnings` lists the build's warning diagnostics.

It raises `ProviderCheckError`, an `AssertionError`, with the message, hint,
and location Studio would show for the first problem found. It blocks until
the check finishes, and inside a running event loop, such as an async test or
a notebook cell, it runs the check on a worker thread. The check also fails
when `inspect()` changes the project, when two inspections differ, when
inspection reports an error, and when the package that defines the provider
imports Studio modules outside `marimo_studio.view_providers` and
`marimo_studio.view_providers.testing`.

### Notebook records

`StarterContext.notebook` is a `NotebookSpec`:

```text
NotebookSpec(
    path: Path,
    revision: str,
    cells: tuple[CellSpec, ...],
    app_config: dict[str, Any],
)

CellRef(fingerprint: str, layout_fingerprint: str, occurrence: int = 0)

SourceSpan(start_line: int, end_line: int, start_column: int = 0, end_column: int = 0)

CellConfigSpec(column: int | None, disabled: bool, hide_code: bool)
```

`NotebookSpec.cells` stays in document order, and `app_config` is detached
JSON-compatible configuration. `by_ref()` indexes cells by `CellRef`, and
`named_cells()` indexes them by marimo name. The revision changes when any
field a provider can see changes.

`CellRef` identifies one saved cell. Treat it as opaque: `str(ref)` returns its
`cell:v1:` form and `CellRef.parse(value)` restores it. `SourceSpan` locates a
cell in the saved notebook in the coordinates of marimo's static compiler.
`CellConfigSpec` holds the cell's layout column, disabled state, and code
visibility.

`CellSpec` holds one saved cell:

| Field                          | Contract                                                           |
| ------------------------------ | ------------------------------------------------------------------ |
| `ref`                          | `CellRef` used by cell targets and dependency edges                |
| `runtime_id`                   | Cell ID in the compiled notebook                                   |
| `index`                        | Zero-based document position                                       |
| `kind`                         | One `CellKind` value                                               |
| `name`                         | marimo cell name, or `None` for an unnamed cell                    |
| `source`                       | `SourceSpan` in the saved notebook                                 |
| `code_sha256` and `preview`    | Source digest and bounded preview text                             |
| `definitions` and `references` | Variable names the cell defines and reads                          |
| `upstream` and `downstream`    | Ordered `CellRef` dependencies                                     |
| `config`                       | Saved `CellConfigSpec`                                             |
| `has_output_expression`        | Whether the cell ends with an output expression                    |
| `may_display_output`           | Whether the cell may display output                                |
| `markdown`                     | Literal Markdown text when static inspection can recover it        |
| `code`                         | Complete source when the inspection requested it, otherwise `None` |

`may_display_output` is `True` when the cell ends in an output expression, when
static analysis finds a marimo output call, or when analysis cannot reach a
definite answer. `has_output_expression` reports the narrower final-expression
case.

### Limits and built-in examples

[Limits](limits.md#provider-records) lists provider record and file budgets.
[Built-in view providers](built-in-providers.md) lists the built-in provider
keys, starters, and provider options.
