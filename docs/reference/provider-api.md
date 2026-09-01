---
title: Add support for another frontend
description: Connect frontend source and its existing build command to Marimo Studio.
---

# Add support for another frontend

A team can keep an existing frontend project and build it inside Studio. A
small Python integration tells Studio:

- which starting files it can create
- which source files people can edit
- which files affect the browser build
- how to produce the browser page Studio serves

Studio calls this integration a **view provider**. Studio continues to own
notebook execution, safe source writes, immutable build inputs, output
validation, the last successful artifact, browser sessions, and agent workflows.

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
dependencies = ["marimo-studio>=0.1,<0.2"]

[project.entry-points."marimo_studio.view_provider"]
report = "acme_views:provider"
```

Studio derives the installed key from the distribution and registration name.
Distribution `acme-views` and registration `report` produce
`acme-views/report`.

## Implement the protocol

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

`ProviderInfo` contains the title and summary shown during view creation, plus
`api_version`. Set `api_version` to `PROVIDER_API_VERSION`.

Studio requires an exact provider API match. Test the provider before expanding
its Studio dependency to a newer minor release. [Compatibility and
support](compatibility.md) owns the current release policy.

## Create starting files

`ProviderStarter` describes one starting point with a provider-local key,
title, summary, and required files. Studio qualifies the local key with the
provider key. Local key `default` from `acme-views/report` becomes
`acme-views/report:default`.

`StarterContext.notebook` is a detached `NotebookSpec` for a saved notebook
revision. Its ordered cells include source, kind, name, literal Markdown,
configuration, definitions, references, and dependency edges. The revision
changes when any provider-visible field changes. Static inspection compiles
this metadata and leaves cell bodies unexecuted.

`CellSpec.may_display_output` is a conservative static signal. It is `True`
when the cell ends in an output expression, when symbolic analysis finds a
Marimo output operation, or when ambiguity, work-budget exhaustion, or the
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

`StarterPlan.files` contains provider-owned files. Studio writes `view.toml`
and the workspace ignore rules. Starting files cannot claim Studio control
paths such as `view.toml`, `.artifacts/`, `.locks/`, or `.gitignore`.

## Inspect the current project

`inspect()` returns `ProjectInspection` with:

- `editor_documents`, the ordered text files shown in Source
- `input_scope`, the exact files and bounded directories that affect a build
- notebook-result declarations found in the source
- source-located diagnostics
- `build_fingerprint`, which changes when provider build behavior changes

Studio watches editor documents and the input scope. It uses the input scope for
safe build snapshots and build identity. Include `view.toml` in the scope and
keep it out of `editor_documents` because Studio owns that file.

An editor document may stay outside `input_scope` when editing it should not
invalidate or rebuild the frontend artifact. Studio still confines reads and
writes to the exact path returned by provider inspection.

Put provider caches beneath `request.cache_root`. Keep generated dependencies
outside a recursive source directory when they do not affect browser output.

`inspect()` is a read-only project operation. Report editable documents, build
inputs, mounts, and diagnostics. Keep reusable downloaded or generated data in
`request.cache_root`.

### Declare projection sites

`ProjectInspection.mounts` connects a projection element in editable source to
the corresponding element in the built artifact. For this one-line
`index.html`:

```html
<marimo-cell name="summary"></marimo-cell>
```

return one deterministic mount from `inspect()`:

```python
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    MountDeclaration,
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

During `build()`, read the accepted site from `request.inspection.mounts` and
add its canonical attribute to the corresponding projection element:

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
the exact input paths, build profile, staging directory, cache directory,
cancellation owner, command budget, and supervised runner.

Run existing frontend commands through `request.runner.run()`. Use a working
directory inside the snapshot, write the browser output beneath
`request.staging_root`, and return the entry HTML document in `BuildResult`.

The entry document needs one `head`, one `body`, and one `#app-shell`. Studio
validates paths, symlinks, file limits, reserved routes, and the complete output
before making the page available.

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

`request.cancellation` supplies the cooperative signal for provider
implementations that run in process. Check `cancelled` around filesystem work
that the runner does not own. A registered callback can interrupt a long-running
library call and should be unregistered when that call completes.

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

After installing the package, verify its registration and starting files:

```console
marimo-studio doctor acme-views/report
marimo-studio starters
```

Test view creation, a successful build, a failed build that leaves the last
successful artifact available, and one notebook result rendered through the
installed package.
