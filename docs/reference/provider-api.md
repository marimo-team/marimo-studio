---
title: Frontend extension API
description: Register a starter, inspect project files, and build browser output through the compact provider protocol.
---

# Frontend extension API

A frontend extension is a Python entry point that creates source files,
inspects a view project, and builds browser files. Studio owns manifests,
artifact publication, browser sessions, notebook execution, and agents.

Register one object:

```toml
[project.entry-points."marimo_studio.view_provider"]
report = "acme_views:provider"
```

The durable provider key is derived from the distribution and entry-point name.
For distribution `acme-views` and entry point `report`, the key is
`acme-views/report`.

## Protocol

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
    ) -> Mapping[PurePosixPath, bytes]: ...

    def inspect(self, request: InspectionRequest) -> ProjectInspection: ...

    def build(self, request: BuildRequest) -> BuildResult: ...
```

All methods are synchronous. Studio runs provider operations outside the
server event loop. `InspectionRequest` and `BuildRequest` supply a supervised
runner, cancellation owner, cache directory, and finite command budget.
The `command_timeout` field is the aggregate budget for commands started through
`request.runner`. Each command timeout is validated and clamped to the budget
remaining. Studio bounds runner output and owns descendant cleanup. Provider
Python runs synchronously outside the server event loop and must return promptly.

## Provider information

`ProviderInfo` contains:

- `title`
- `summary`
- `api_version`

Set `api_version` to the literal provider contract implemented by the package.
Update it when the provider adopts a newer contract.

Provider API 4 uses phase-neutral operation names:

| API 3                | API 4                     |
| -------------------- | ------------------------- |
| `BuildCancellation`  | `ProviderCancellation`    |
| `BuildCommandResult` | `ProviderCommandResult`   |
| `BuildRunner`        | `ProviderRunner`          |
| `request.timeout`    | `request.command_timeout` |

The registry supplies provider identity, distribution, and installed version.

The optional `[options]` table in `view.toml` reaches the provider as a detached
JSON-compatible mapping in `ViewProject.options`. Provider inspection validates
its accepted keys and values and returns source diagnostics for invalid input.

## Starters

`ProviderStarter` contains a provider-local key, title, summary, and the
documents its creation result must contain. Studio qualifies that key with the
provider identity. A `default` key from `acme-views/report` appears as
`acme-views/report:default` in the Agent API, CLI, and browser catalog.

`create()` returns provider-owned files. Studio writes `view.toml` and the
workspace ignore rules.

Starter files cannot claim:

- `view.toml`
- `.artifacts/`
- `.locks/`
- `.gitignore`

Paths are normalized project-relative `PurePosixPath` values. File and
directory collisions are rejected before Studio writes anything.

## Inspection

`ProjectInspection` returns:

- `editor_documents`, the ordered files allowed in the user-facing Source editor
- `input_scope`, containing exact files and bounded recursive directories
- mount declarations with allowed targets or wildcard access
- diagnostics
- one provider build fingerprint

Studio watches `editor_documents` and `input_scope`. It enumerates
`input_scope` once and uses those files for revisions, snapshots, and
`BuildRequest.inputs`. An editor document can remain outside that scope when
editing it should not invalidate the browser artifact. Studio still confines
reads and writes to the exact provider-authorized document path. Keep generated
dependencies and provider caches outside declared recursive directories when
they do not affect browser output. Provider caches belong beneath
`request.cache_root`.

Studio owns `view.toml`, which providers include in `input_scope` and keep
outside `editor_documents`. Diagnostics use stable kebab-case codes and
optional source locations.

The build fingerprint identifies provider-owned analysis and build behavior.
Studio combines it with the provider distribution, version, API version, and
its instrumentation contract before computing build identity.

## Build

`BuildRequest` contains an immutable project snapshot, its accepted inspection,
the exact snapshot inputs, profile, staging directory, cache directory, input
revision, cancellation owner, aggregate command budget, and supervised command
runner.
`request.runner.run()` accepts a command, snapshot-contained working directory,
timeout, and optional complete environment. Write browser files beneath
`staging_root` and return the entry document in `BuildResult`.

The returned entry document is UTF-8 HTML with one `head`, one `body`, and one
`#app-shell`. Runtime tags and attributes such as `marimo-cell`,
`marimo-output`, `mo-value`, and `data-marimo-studio-site` are reserved for the
projection contract. Each declared mount in the built document carries the
attribute returned by `mount_attribute(site.id)`. The attribute value must
match the corresponding `MountDeclaration.id`.

Providers build candidate files in `staging_root`. Studio validates path
containment, symlinks, file budgets, reserved routes, and the complete
candidate before publishing it atomically.

## Minimal provider

```python
import shutil
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    BuildResult,
    ProjectInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
)

ENTRY = PurePosixPath("index.html")


class ReportProvider:
    info = ProviderInfo(
        title="Report",
        summary="Builds one HTML report.",
        api_version=4,
    )
    starter = ProviderStarter(
        key="default",
        title="Report",
        summary="One editable HTML document.",
        documents=(ENTRY,),
    )

    def availability(self, project=None):
        return ProviderAvailability(True)

    def starters(self):
        return (self.starter,)

    def create(self, starter, context):
        return {
            ENTRY: b'''<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>Report</title></head>
  <body><main id="app-shell"></main></body>
</html>
'''
        }

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

Run `marimo-studio doctor acme-views/report` after installation. Test
one creation, one build, one failed build that retains the last publication,
and one browser mount through the installed package.
