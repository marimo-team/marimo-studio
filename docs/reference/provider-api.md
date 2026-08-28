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
- how to produce the page served to the audience

Studio calls this integration a **view provider**. Studio continues to own
notebook execution, safe source writes, build isolation, validation, the last
successful page, browser sessions, and agent workflows.

## Register the provider

Publish one object through Python package metadata:

```toml
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
    ) -> Mapping[PurePosixPath, bytes]: ...

    def inspect(self, request: InspectionRequest) -> ProjectInspection: ...

    def build(self, request: BuildRequest) -> BuildResult: ...
```

Provider methods are synchronous. Studio runs them away from the server event
loop and supplies cooperative cancellation plus a supervised command runner.

`ProviderInfo` contains the title and summary shown during page creation, plus
`api_version`. Set `api_version` to `PROVIDER_API_VERSION`.

## Create starting files

`ProviderStarter` describes one starting point with a provider-local key,
title, summary, and required files. Studio qualifies the local key with the
provider key. Local key `default` from `acme-views/report` becomes
`acme-views/report:default`.

`create()` returns the provider-owned files. Studio writes `view.toml` and the
workspace ignore rules. Starting files cannot claim Studio control paths such
as `view.toml`, `.artifacts/`, `.locks/`, or `.gitignore`.

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

## Minimal provider

```python
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

After installing the package, verify its registration and starting files:

```console
marimo-studio doctor acme-views/report
marimo-studio starters
```

Test page creation, a successful build, a failed build that leaves the last
successful page available, and one notebook result rendered through the
installed package.
