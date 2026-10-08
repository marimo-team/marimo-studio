---
title: View provider API
description: Register a view provider that creates, inspects, and builds frontend view projects.
---

# View provider API

A view provider connects a frontend project format and its build command to
Studio. It tells Studio which starters it offers, which Source documents people
edit, which build inputs affect the page, where the page shows notebook
results, and how to build the page or document that Studio publishes.

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

Each term names one concept, and the third column names the record or field
that holds it.

| Term             | Meaning                                                                    | In the API               |
| ---------------- | -------------------------------------------------------------------------- | ------------------------ |
| View project     | The directory that holds one view's files                                  | `ViewProject`            |
| View manifest    | `view.toml`, which records the provider key and provider options           | `ViewProject.manifest`   |
| Provider key     | Distribution and registration name, such as `acme-views/report`            | `ViewProject.provider`   |
| Provider options | The `[options]` table in `view.toml`                                       | `ViewProject.options`    |
| Starter          | A template for a new view, shown in the **New view** picker                | `ProviderStarter`        |
| Starter key      | The starter's name within its provider, such as `default`                  | `ProviderStarter.key`    |
| Starter ID       | Provider key and starter key, such as `acme-views/report:default`          | `CheckedView.starter`    |
| Cell target      | The name a `<marimo-cell>` host uses: a marimo cell name or a Studio alias | `StarterCellTarget`      |
| Source document  | A file shown in Studio's Source panel                                      | `SourceDocument`         |
| Build input      | A file or directory the build reads. A change rebuilds the view            | `BuildInput`             |
| Projection host  | `<marimo-cell>`, `<marimo-output>`, or an element with `mo-value`          |                          |
| Projection site  | The source location, kind, and targets of one projection host              | `ProjectionSite`         |
| Target           | The cell name or value selector that a host shows                          | `ProjectionSite.targets` |
| Build snapshot   | A private copy of the build inputs with a site ID on every host            | `BuildRequest.project`   |
| Entry document   | The HTML page a build returns                                              | `BuildResult.document`   |
| Accept list      | The image types an output host can show, in preference order               | `ProjectionSite.accept`  |
| Diagnostic       | A problem with a code, message, hint, and optional source location         | `ProjectDiagnostic`      |

## Register the provider

Publish one provider object through Python package metadata. Bound the Studio
dependency to the minor line that the provider has tested:

```toml
[project]
name = "acme-views"
version = "0.1.0"
dependencies = ["marimo-studio>=0.4,<0.5"]

[project.entry-points."marimo_studio.view_provider"]
report = "acme_views:provider"
```

Studio derives the provider key from the canonical distribution name and the
entry point registration. Distribution `acme-views` and registration `report`
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

Provider methods are synchronous. Studio runs them away from the server event
loop and supplies a cancellation owner and a supervised command runner. Import
every name from `marimo_studio.view_providers`. Studio's other modules change
without notice.

`ProviderInfo` holds the title and summary shown in the view picker and in
diagnostics, plus `options`, the provider options the provider reads.

## Create starting files

`starters()` returns `ProviderStarter` records. Each has a starter key, a title
and summary for the picker, and `documents`, the Source documents a new view
starts with. Studio prefixes the starter key with the provider key to form the
starter ID: starter key `default` from `acme-views/report` becomes
`acme-views/report:default`.

`create()` returns a `StarterPlan`. `StarterPlan.files` holds every file the
provider writes, and it must include each path in `ProviderStarter.documents`.
Studio writes `view.toml` and workspace ignore rules itself. Starter files
cannot claim Studio paths such as `view.toml`, `.artifacts/`, `.locks/`, or
`.gitignore`. A starter may ship `AGENTS.md` and `DESIGN.md` for coding agents,
and Studio shows them in Source when they exist.

`StarterContext.notebook` is a detached `NotebookSpec` for the saved notebook.
Its ordered cells include source, kind, name, literal Markdown, configuration,
definitions, references, and dependency edges. `create()` receives saved
notebook code, so install a provider only when its package is trusted with that
source.

`StarterContext.cell_targets` maps each ordinary cell to a `StarterCellTarget`.
The target is the cell's marimo name, an existing Studio alias, or a new alias
that Studio proposes for an unnamed cell. `StarterContext.output_cells` returns
the targets for cells that marimo runs and that may display output, in notebook
order. It skips disabled cells and cells downstream of a disabled cell.

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
changes notebook-local configuration, Studio calls `create()` a second time
with the notebook as it will be saved. Return the same `cell_targets` from both
calls.

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
use `__NOTEBOOK_LABEL_HTML__`, `__VIEW_HEADING_HTML__`,
`__NOTEBOOK_LABEL_JSON__`, and `__VIEW_HEADING_JSON__`. The `_JSON` markers
produce a JSON string literal that is safe inside a `<script>` element, and
`script_json()` produces the same form for your own markers. Include the
`files/` directories in the package build so they ship in the wheel.

## Inspect the project

`inspect()` returns a `ProjectInspection`:

| Field         | Holds                                                 |
| ------------- | ----------------------------------------------------- |
| `documents`   | The Source documents, in tab order                    |
| `inputs`      | The build inputs: exact files and bounded directories |
| `sites`       | One projection site per projection host               |
| `diagnostics` | Problems found in the project                         |

Studio watches the Source documents and the build inputs. The build inputs
also decide the project revision and the contents of the build snapshot.
Studio adds `view.toml` to the build inputs and lists `view.toml`, `AGENTS.md`,
and `DESIGN.md` in Source. A Source document can stay out of the build inputs
when editing it should not rebuild the view.

`project_files(project, roots=..., exclude=...)` lists the files a build can
read, skipping hidden top-level entries and the files Studio owns. Use it
for a project whose build inputs follow its directory layout.

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

An invalid value raises `ProviderError` located at `view.toml`, and Studio
shows it as a diagnostic.

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
the build input paths, the project revision, the build profile, three working
directories, a cancellation owner, a command budget, and a supervised runner.

Write the output beneath `request.staging_root` and return the entry document
in `BuildResult`. `copy_inputs(request, destination)` copies every build input
except `view.toml`. A build that copies its sources is two lines:

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

`request.cache_root` persists between builds. The browser shows notebook
results in the entry document's projection hosts.

The `development` profile builds Studio Preview. The `production` profile
builds run mode and static export. Each profile keeps its own build state and
publication.

An HTML entry document needs one `head`, one `body`, and one `#app-shell`.
Studio validates paths, symlinks, file limits, reserved routes, projection
sites, and the complete output before publication.

## Report problems

Raise `ProviderError` from `inspect()` or `build()` when the author can fix
the problem in the project:

```python
raise ProviderError(
    "index.html links missing.css.",
    hint="Create missing.css or remove the link.",
    source=SourceLocation(PurePosixPath("index.html"), 3, 5),
)
```

`hint` names the next step the author can take. Put tool output, such as a
compiler's error text, in the message. Studio shows the message and hint
beside `source` in Source and keeps the last published view. When `inspect()`
raises, Studio opens the `source` file in Source so the author can repair it
there. When a build error's `source` names a
file outside Source, Studio puts that location at the start of the message.
Studio strips surrounding whitespace from the message and hint.

Return diagnostics in `ProjectInspection.diagnostics` or
`BuildResult.diagnostics` to report several problems at once, or a warning that
still publishes. Any other exception is a provider failure, and Studio reports
it with the provider key.

## Run commands

`request.runner.run(command, cwd=...)` starts a supervised child command. Its
`cwd` must be inside `request.project.root`, which holds `request.work_root`
and `request.staging_root`.

- `timeout` is a finite positive number of seconds, 120 by default. Every
  command in one request also shares `request.command_timeout` as a total
  budget.
- `environment=None` inherits the Studio process environment. A mapping
  replaces the whole environment for the command, so pass
  `environment={**os.environ, ...}` to add variables.
- The result holds `returncode`, bounded `stdout`, and bounded `stderr`.

The runner raises `ProviderCommandError` when a command exceeds its budget or
its output limit, or when the operation is cancelled. Let it propagate.

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
        ["pandoc", "--version"],
        minimum="3.0",
        install="Install Pandoc 3.0 or newer from https://pandoc.org/installing.html.",
    )
```

Studio shows `reason` and `action` in the view picker and in
`marimo-studio doctor`. The process remembers a reported version until the
executable changes. Studio records the `availability()` version with each
build, so a tool upgrade rebuilds the views that use the provider.

## Record reference

### Provider records

```text
ProviderInfo(title: str, summary: str, options: frozenset[str] = frozenset())

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
)
```

Studio validates `ProviderInfo` when it discovers the provider. Return `reason`
and an actionable `action` when `available` is false. `ProviderStarter.key` is
the starter key, and `documents` lists the Source documents a new view starts
with.

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

`manifest` is the path of `view.toml`, and `provider` is the provider key.
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

`StarterContext.output_cells` returns the cell targets for cells that marimo
runs and that may display output. `app_title` returns the notebook's configured
app title or `None`, and `notebook_label` returns the app title or a readable
form of the notebook filename.

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

SourceLocation(path: PurePosixPath, line: int, column: int)
```

`SourceDocument.path` is a contained, project-relative POSIX path, `language`
is the editor language ID, and `label` is an optional tab name. A directory
`BuildInput` covers every file beneath it, within Studio's input limits.
`ProjectionSite.targets` must be non-empty and unique, and `"*"` permits any
valid target of `kind`.

`accept` lists lowercase `type/subtype` media types in order of preference,
such as `("image/svg+xml", "image/png")`. Only an output site takes one, and it
lists images a page shows: `image/svg+xml`, `image/png`, `image/jpeg`, or
`image/gif`. Studio renders the output's value in the first type the value
supports through marimo-export's
[`represent()`](https://marimo-team.github.io/marimo-export/reference/python/values),
whatever output settings the notebook uses. An output site without `accept`
shows marimo's native output. A `"*"` output site declares no `accept` and
shows each target in the form its literal sites declare. Every site of one
output target in a view uses the same accept list, and a different list reports
`output-accept-conflict`.
`SourceLocation` lines and columns are one-based.

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
    work_root: Path,
    cache_root: Path,
    cancellation: ProviderCancellation,
    runner: ProviderRunner,
    command_timeout: float,
)

BuildResult(
    document: PurePosixPath | None,
    diagnostics: tuple[ProjectDiagnostic, ...] = (),
)
```

`BuildRequest.inputs` lists every build input file, with directories expanded.
`staging_root` receives the output, `work_root` is an empty directory for
intermediate files, and `cache_root` persists between builds. Return
`document=None` when diagnostics prevent publication.

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
`stdout`, and bounded `stderr`. The runner and `raise_if_cancelled()` raise
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

copy_inputs(request: BuildRequest, destination: Path) -> None

project_path(value: object, *, field: str = "Project path") -> PurePosixPath

html_sites(
    path: PurePosixPath,
    source: bytes,
) -> tuple[tuple[ProjectionSite, ...], tuple[ProjectDiagnostic, ...]]

parse_accept(kind: ProjectionKind, text: str | None) -> tuple[str, ...]

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
directories by name. Hidden top-level entries such as `.env`, `view.toml`,
`AGENTS.md`, and `DESIGN.md` are skipped. It raises `ProviderError` for a
symlink or a project over the [input limits](limits.md#provider-records).

`copy_inputs()` copies each path in `request.inputs` except `view.toml` to the
same relative path beneath `destination`.

`project_path()` normalizes a project-relative POSIX path. It raises
`ValueError` for absolute paths, `..` segments, backslashes, and names that are
not portable across operating systems.

`html_sites()` parses `source` as HTML and returns its projection sites with
diagnostics for invalid hosts. `source` holds the file bytes as stored, so each
`offset` points into the same bytes Studio marks. When the markup cannot be
parsed, the result keeps the sites found before the parse error.

`parse_accept()` reads a host's `accept` attribute text, such as
`"image/svg+xml, image/png"`, into lowercase media types in preference order.
Pass `None` for a host without the attribute to get an empty tuple. Spaces or
commas separate the types, and each must be `image/svg+xml`, `image/png`,
`image/jpeg`, or `image/gif`. It raises `ValueError` for an `accept` on a cell
or value host, an empty list, a malformed or repeated type, or another media
type. Report the message as a `projection-accept-invalid` diagnostic at the
host, and keep reporting the file's other hosts.

`probe_tool()` finds `command[0]` on `PATH` unless it is a path, runs it, and
compares the first dotted version in its output with `minimum`. It reads
standard error when standard output has none, and a prerelease such as
`2.9.5-rc.1` compares below its release. The command has
30 seconds to finish. An unavailable result carries a `reason`, such as a
timeout, an exit status, or an old version, and `install` as its `action`. The
process remembers a reported version until the executable changes, and checks
again after a failed or cancelled check. It raises `ProviderCommandError` when the operation
is cancelled.

### `check_provider()`

```text
from marimo_studio.view_providers.testing import check_provider

check_provider(
    provider: ViewProvider | str,
    *,
    key: str = "local-provider/provider",
    notebook: str | Path | None = None,
    options: Mapping[str, JsonValue] | None = None,
) -> tuple[CheckedView, ...]

CheckedView(
    starter: str,
    documents: tuple[PurePosixPath, ...],
    published: Mapping[PurePosixPath, bytes],
    warnings: tuple[str, ...],
)
```

`check_provider()` runs each starter through the same steps as Studio. It
creates a view next to a sample notebook, inspects it twice, and builds and
publishes it:

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
options of each view. `CheckedView.starter` is the starter ID, `documents` lists the view's Source
documents, and `warnings` lists the build's warning diagnostics.

It raises `ProviderCheckError`, an `AssertionError`, with the message, hint,
and location Studio would show for the first problem found. It blocks until
the check finishes, and inside a running event loop, such as an async test or
a notebook cell, it runs the check on a worker thread. The check also
fails when `inspect()` changes the project, when two inspections differ, when
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
