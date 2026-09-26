---
title: View provider API
description: Register a view provider that creates, inspects, and builds frontend view projects.
---

# View provider API

A view provider connects an existing frontend project and build command to
Studio. It tells Studio:

- which starters it offers
- which Source documents people can edit
- which build inputs affect the browser artifact
- how to produce the browser files Studio validates and publishes

Studio owns notebook execution, conditional Source writes, immutable build
snapshots, artifact validation and publication, presentations, browser
sessions, and agent workflows.

::: warning View providers are trusted code
An installed provider runs Python and child commands with the current user's
filesystem permissions, environment variables, and network access. Studio runs
third-party calls in owned child processes to bound deadlines, output, and
cleanup. That process boundary is lifecycle containment, not a security sandbox.
Review the provider package and its dependencies before installing it in an
environment that contains credentials or private notebook source.
:::

## Register the provider

Publish one object through Python package metadata. Bound the Studio dependency
to the minor line that the provider has tested:

```toml
[project]
name = "acme-views"
version = "0.1.0"
dependencies = ["marimo-studio"]

[project.entry-points."marimo_studio.view_provider"]
report = "acme_views:provider"
```

Studio derives the provider key from the canonical distribution name and entry
point registration. Distribution `acme-views` and registration `report`
produce `acme-views/report`. The key is an opaque product identity. It is not a
Python import path.

One installed registration owns one provider key. Studio rejects duplicate
registrations for the same key. A view stores its provider key in `view.toml`.
Studio Source writes preserve that key. Create another view when selecting a
different provider through supported authoring operations.

## Implement the protocol

Implement the `ViewProvider` protocol and publish one provider object from the
registered entry point:

```python
class ViewProvider(Protocol):
    info: ProviderInfo

    def availability(
        self,
        project: ViewProject | None = None,
    ) -> ProviderAvailability: ...

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
loop and supplies a cancellation contract plus a supervised command runner.

`ProviderInfo` contains the title and summary used by provider discovery and
diagnostics, plus `api_version`. Starter title and summary appear during view
creation. Set `api_version` to `PROVIDER_API_VERSION`.

Studio requires an exact provider API match. Test the provider before expanding
its Studio dependency to a newer minor release. [Compatibility and
support](compatibility.md) owns the current release policy.

### Exported type aliases

| Name               | Type and use                                                                                         |
| ------------------ | ---------------------------------------------------------------------------------------------------- |
| `BuildProfile`     | `Literal["development", "production"]` passed to `BuildRequest.profile`                              |
| `CellKind`         | `Literal["cell", "setup", "function", "class", "unparsable"]` returned by static notebook inspection |
| `DocumentAccess`   | `Literal["edit", "read"]` used by `SourceDocument.access`                                            |
| `JsonValue`        | Recursive JSON-compatible scalar, list, or string-keyed dictionary used by provider options          |
| `ProjectInputKind` | `Literal["file", "directory"]` used by `ProjectInput.kind`                                           |
| `ProjectionKind`   | `Literal["cell", "output", "value"]` used by `MountDeclaration.kind`                                 |

`PROVIDER_API_VERSION` is the integer that a provider assigns to
`ProviderInfo.api_version`. Studio 0.2 requires an exact match.

## Create starting files

`ProviderStarter` describes one starter with a provider-local key,
title, summary, and initial Source document plan. Studio qualifies the local
key with the provider key. Local key `default` from `acme-views/report` becomes
`acme-views/report:default`.

`documents` advertises the Source documents a new project is expected to
expose. `StarterPlan.files` is the complete provider-owned file set. Every
advertised document must appear in that file set. Studio adds `view.toml` and
workspace ignore rules outside the provider plan.

`StarterContext.notebook` is a detached `NotebookSpec` for a saved notebook
revision. Its ordered cells include source, kind, name, literal Markdown,
configuration, definitions, references, and dependency edges. The revision
changes when any provider-visible field changes. Static inspection compiles
this metadata and leaves cell bodies unexecuted.

`CellSpec.may_display_output` is a conservative static signal. It is `True`
when the cell ends in an output expression, when symbolic analysis finds a
marimo output operation, or when ambiguity, work-budget exhaustion, or the
recursion limit prevents a definitive result. Use it to seed an editable
starter while retaining likely output cells. `CellSpec.has_output_expression`
reports the narrower final-expression case.

`StarterContext.cell_targets` maps each ordinary cell to a
`StarterCellTarget`. The target uses a native cell name, an existing Studio
alias, or a collision-free alias proposed for an anonymous cell. Generated
source uses `target.target` and returns the records it consumed through
`StarterPlan.cell_targets`:

```python
import html
from pathlib import PurePosixPath

from marimo_studio.view_providers import StarterPlan

ENTRY = PurePosixPath("index.html")


def create(starter, context):
    selected = tuple(
        context.cell_targets[cell.ref]
        for cell in context.notebook.cells
        if cell.kind == "cell" and not cell.config.disabled
        if cell.may_display_output
    )
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

Studio validates `StarterPlan.cell_targets` against the supplied context, then
commits required aliases with the project files. A notebook change or alias
conflict before commit rejects the complete creation transaction. The
provider's `inspect()` implementation reports mount sites and their allowed
target sets after the project exists.

Studio may call `create()` twice when notebook-local configuration changes
source locations. The accepted call receives the prospective committed
notebook. Return the same selected `cell_targets` for both calls.

`create()` receives saved notebook code. Install a provider when its package is
trusted with that source. Runtime values and cell outputs reach the generated
page through Studio projections when the view runs.

`StarterPlan.files` contains provider-owned files. Starting files cannot claim
Studio control paths such as `view.toml`, `.artifacts/`, `.locks/`, or
`.gitignore`.

## Inspect the current project

`inspect()` returns `ProjectInspection` with:

- `editor_documents`, the ordered UTF-8 files shown in Source
- `input_scope`, the exact files and bounded directories that affect a build
- notebook-result declarations found in the source
- source-located diagnostics
- `build_fingerprint`, which changes when provider build behavior changes

Studio watches Source documents and the input scope. It uses the input scope for
immutable build snapshots and project revision identity. Include `view.toml`
in the scope and keep it out of `editor_documents` because Studio owns and
exposes that Source document independently.

An editor document may stay outside `input_scope` when editing it should not
invalidate or rebuild the frontend artifact. Studio still confines reads and
writes to the exact path returned by provider inspection.

Put provider caches beneath `request.cache_root`. Keep generated dependencies
outside a recursive source directory when they do not affect browser output.

`inspect()` is a read-only project operation. Report editable documents, build
inputs, mounts, and diagnostics. Keep reusable downloaded or generated data in
`request.cache_root`.

### Declare projection sites

`ProjectInspection.mounts` connects a projection host in authored source to the
corresponding host in the built artifact. For this one-line `index.html`:

```html
<marimo-cell name="summary"></marimo-cell>
```

return one deterministic mount from `inspect()`:

```python
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    MountDeclaration,
    ProjectInput,
    ProjectInspection,
    SourceDocument,
    SourceLocation,
    mount_attribute,
)

ENTRY = PurePosixPath("index.html")
SUMMARY_SITE = MountDeclaration(
    id="report-summary",
    kind="cell",
    source=SourceLocation(ENTRY, line=1, column=1),
    allowed_targets=("summary",),
)

def inspect(self, request):
    return ProjectInspection(
        editor_documents=(SourceDocument(ENTRY, "html", "edit"),),
        input_scope=(
            ProjectInput(ENTRY, "file"),
            ProjectInput(PurePosixPath("view.toml"), "file"),
        ),
        mounts=(SUMMARY_SITE,),
        diagnostics=(),
        build_fingerprint="report-v1",
    )
```

`source` points to the projection declaration in an editor document. Line and
column numbers are one-based. The mount ID must be unique within the inspection
and remain stable for the same source site.

During `build()`, read the accepted site from `request.inspection.mounts`.
`mount_attribute` returns the canonical attribute to add to the corresponding
projection element:

```python
site = request.inspection.mounts[0]
attribute_name, attribute_value = mount_attribute(site.id)
```

For `SUMMARY_SITE`, the built artifact contains:

```html
<marimo-cell name="summary" data-marimo-studio-site="report-summary"></marimo-cell>
```

Add the attribute to the staged artifact and keep it out of editable source.
Studio reserves `data-marimo-studio-site` for artifact instrumentation.

The mount `kind` must match its projection element: `cell` for `marimo-cell`,
`output` for `marimo-output`, and `value` for an element with `mo-value`.
`allowed_targets=("summary",)` authorizes that exact notebook result. Use
`None` when source chooses targets dynamically. It permits any valid target for
that projection kind.

## Build browser files

`BuildRequest` contains a read-only project snapshot, its accepted inspection,
the exact input paths, project revision, build profile, staging directory,
cache directory, cancellation owner, command budget, and supervised runner.

Run existing frontend commands through `request.runner.run()`. Use a working
directory inside the snapshot, write the browser output beneath
`request.staging_root`, and return the entry HTML document in `BuildResult`.

`development` builds Studio Preview. `production` builds run mode and static
export. Each profile keeps independent attempt and retained-publication state.

The entry document needs one `head`, one `body`, and one `#app-shell`. Studio
validates paths, symlinks, file limits, reserved routes, mount instrumentation,
and the complete output before publication.

## Bound commands and cancellation

`request.runner.run(command, cwd=...)` starts a supervised child command with a
working directory inside `request.project.root`. It accepts these keyword
arguments:

- `timeout` is a finite positive number of seconds. The default is 120 seconds.
  Every command in one request also shares `request.command_timeout` as an
  aggregate budget.
- `environment=None` inherits the current Studio process environment. Passing a
  mapping replaces that environment for the child command.
- The result contains `returncode`, bounded `stdout`, and bounded `stderr`.
  Convert a nonzero return code into a source-located `ProjectDiagnostic` when a
  reader can repair the build input.

`request.cancellation` is a `ProviderCancellation` object that supplies the
cooperative signal for provider implementations that run in process. Check
`cancelled` around filesystem work that the runner does not own. A registered
callback can interrupt a long-running library call and should be unregistered
when that call completes.

Installed third-party calls also have an outer process owner. Cancellation, a
deadline, or excessive command output can terminate that process tree before
the provider observes the cooperative signal or runs cleanup code. Write
candidate browser files beneath `request.staging_root`, keep reusable state
beneath `request.cache_root`, and leave durable workspace publication to Studio.

## Minimal provider

`ReportProvider` focuses on registration, source discovery, and artifact
publication. Add the projection-site contract when its page contains
`marimo-cell`, `marimo-output`, or `mo-value` hosts.

```python
import html
import shutil
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    PROVIDER_API_VERSION,
    BuildResult,
    ProjectInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    StarterPlan,
)

ENTRY = PurePosixPath("index.html")


class ReportProvider:
    info = ProviderInfo(
        title="Report",
        summary="Creates one editable HTML report.",
        api_version=PROVIDER_API_VERSION,
    )
    starter = ProviderStarter(
        key="default",
        title="Report",
        summary="Start from one HTML document.",
        documents=(ENTRY,),
    )

    def availability(self, project=None):
        return ProviderAvailability(True)

    def starters(self):
        return (self.starter,)

    def create(self, starter, context):
        title = context.notebook.app_config.get("app_title")
        if not isinstance(title, str) or not title.strip():
            title = context.notebook_name.replace("-", " ").title()
        document = f'''<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>{html.escape(title)}</title></head>
  <body><main id="app-shell"></main></body>
</html>
'''
        return StarterPlan(files={ENTRY: document.encode()}, cell_targets=())

    def inspect(self, request):
        manifest = PurePosixPath("view.toml")
        return ProjectInspection(
            editor_documents=(SourceDocument(ENTRY, "html", "edit"),),
            input_scope=(
                ProjectInput(ENTRY, "file"),
                ProjectInput(manifest, "file"),
            ),
            mounts=(),
            diagnostics=(),
            build_fingerprint="report-v1",
        )

    def build(self, request):
        shutil.copy2(request.project.root / ENTRY, request.staging_root / ENTRY)
        return BuildResult(ENTRY, ())


provider = ReportProvider()
```

After installing the package, verify its registration and starter catalog:

```console
marimo-studio doctor acme-views/report
marimo-studio starters
```

Test view creation, a successful build, a failed build that leaves the last
successful artifact available, and one notebook result rendered through the
installed package.

## Record reference

### `CellRef`

```text
CellRef(
    fingerprint: str,
    layout_fingerprint: str,
    occurrence: int = 0,
)
```

Identifies one saved notebook cell from semantic and layout fingerprints.
Providers receive `CellRef` values as keys in `StarterContext.cell_targets` and
return the selected values through `StarterCellTarget`. Treat received values
as opaque identities. `str(ref)` returns the serialized `cell:v1:` form and
`CellRef.parse(value)` restores it.

### `SourceSpan`

```text
SourceSpan(
    start_line: int,
    end_line: int,
    start_column: int = 0,
    end_column: int = 0,
)
```

Locates one cell in the saved notebook. Lines and columns use the coordinates
reported by marimo's static notebook compiler.

### `CellConfigSpec`

```text
CellConfigSpec(
    column: int | None,
    disabled: bool,
    hide_code: bool,
)
```

Contains the saved cell layout column, execution-disabled state, and code
visibility setting.

### `CellSpec`

`CellSpec` contains the provider-visible static record for one saved cell:

| Field                          | Contract                                                                  |
| ------------------------------ | ------------------------------------------------------------------------- |
| `ref`                          | Semantic `CellRef` used by starter target records and dependency edges    |
| `runtime_id`                   | Cell ID in the compiled notebook snapshot                                 |
| `index`                        | Zero-based document position                                              |
| `kind`                         | One `CellKind` value                                                      |
| `name`                         | Native marimo cell name, or `None` for an anonymous cell                  |
| `source`                       | `SourceSpan` in the saved notebook                                        |
| `code_sha256` and `preview`    | Source digest and bounded preview text                                    |
| `definitions` and `references` | Variable names produced and consumed by the cell                          |
| `upstream` and `downstream`    | Ordered semantic `CellRef` dependencies                                   |
| `config`                       | Saved `CellConfigSpec`                                                    |
| `has_output_expression`        | Whether the cell ends with an output expression                           |
| `may_display_output`           | Conservative signal for starter projection selection                      |
| `markdown`                     | Literal Markdown text when static inspection can recover it               |
| `code`                         | Complete source when the owning inspection requested it, otherwise `None` |

### `NotebookSpec`

```text
NotebookSpec(
    path: Path,
    revision: str,
    cells: tuple[CellSpec, ...],
    app_config: dict[str, Any],
)
```

Describes the saved notebook snapshot passed to `StarterContext`. `cells` stays
in document order. `app_config` is detached JSON-compatible configuration.
`by_ref()` indexes cells by semantic identity, `named_cells()` indexes native
names, and `to_dict()` returns the schema 1 record.

### `ProviderInfo`

```text
ProviderInfo(title: str, summary: str, api_version: int)
```

Studio snapshots and validates this record during provider discovery. The
supported `api_version` is `PROVIDER_API_VERSION`.

### `ProviderAvailability`

```text
ProviderAvailability(
    available: bool,
    version: str | None = None,
    reason: str | None = None,
    action: str | None = None,
)
```

Return `reason` and an actionable `action` when `available` is false.

### `ProviderStarter`

```text
ProviderStarter(
    key: str,
    title: str,
    summary: str,
    documents: tuple[PurePosixPath, ...],
)
```

`key` is local to the provider. `documents` is the initial Source document
plan, not the complete generated file set.

### `ViewProject`

```text
ViewProject(
    name: str,
    root: Path,
    manifest: Path,
    provider: str,
    options: Mapping[str, JsonValue],
)
```

`options` is detached, validated JSON-compatible data from `view.toml`.

### `SourceDocument`

```text
SourceDocument(
    path: PurePosixPath,
    language: str,
    access: Literal["edit", "read"],
    label: str | None = None,
)
```

`path` is contained project-relative POSIX text. `language` is the editor
language ID. `label` supplies an optional display name.

### `ProjectInput`

```text
ProjectInput(
    path: PurePosixPath,
    kind: Literal["file", "directory"],
)
```

A directory is a bounded recursive build input. Studio snapshots the normalized
file inventory before calling `build()`.

### `SourceLocation`

```text
SourceLocation(path: PurePosixPath, line: int, column: int)
```

Line and column are one-based safe integers.

### `MountDeclaration`

```text
MountDeclaration(
    id: str,
    kind: Literal["cell", "output", "value"],
    source: SourceLocation,
    allowed_targets: tuple[str, ...] | None,
)
```

Finite `allowed_targets` must be non-empty and unique. `None` declares a
dynamic site. The provider must instrument the matching artifact host with
`mount_attribute(id)`.

### `ProjectDiagnostic`

```text
ProjectDiagnostic(
    code: str,
    severity: Literal["warning", "error"],
    message: str,
    hint: str = "",
    source: SourceLocation | None = None,
)
```

An error diagnostic blocks publication. Add `source` and `hint` when a Source
edit can repair it.

### `ProjectInspection`

```text
ProjectInspection(
    editor_documents: tuple[SourceDocument, ...],
    input_scope: tuple[ProjectInput, ...],
    mounts: tuple[MountDeclaration, ...],
    diagnostics: tuple[ProjectDiagnostic, ...],
    build_fingerprint: str,
)
```

Change `build_fingerprint` when provider behavior can change artifact bytes for
unchanged project inputs.

### `StarterContext` and `StarterPlan`

```text
StarterContext(
    view_name: str,
    notebook_name: str,
    notebook: NotebookSpec,
    cell_targets: Mapping[CellRef, StarterCellTarget],
)

StarterPlan(
    files: Mapping[PurePosixPath, bytes],
    cell_targets: tuple[StarterCellTarget, ...],
)
```

`StarterCellTarget(cell, target)` records the exact context entry consumed by
generated projection source.

### `InspectionRequest`

```text
InspectionRequest(
    project: ViewProject,
    runner: ProviderRunner,
    cancellation: ProviderCancellation,
    cache_root: Path,
    command_timeout: float,
)
```

Inspection is read-only for the project. Reusable provider cache data belongs
beneath `cache_root`.

### `BuildRequest` and `BuildResult`

```text
BuildRequest(
    project: ViewProject,
    inspection: ProjectInspection,
    inputs: tuple[PurePosixPath, ...],
    project_revision: str,
    profile: Literal["development", "production"],
    staging_root: Path,
    cache_root: Path,
    cancellation: ProviderCancellation,
    runner: ProviderRunner,
    command_timeout: float,
)

BuildResult(
    document: PurePosixPath | None,
    diagnostics: tuple[ProjectDiagnostic, ...],
)
```

Write candidate browser files beneath `staging_root`. Return `document=None`
when diagnostics prevent an entry document from being published.

### `ProviderRunner`

```text
runner.run(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float = 120.0,
    environment: Mapping[str, str] | None = None,
) -> ProviderCommandResult
```

`ProviderCommandResult` contains `returncode`, bounded `stdout`, and bounded
`stderr`. `environment=None` inherits the Studio process environment. A mapping
replaces the child environment.

### Limits and built-in examples

[Limits](limits.md#provider-records) lists provider record and file budgets.
[Built-in view providers](built-in-providers.md) lists the bundled provider
keys, starters, and supported options.
