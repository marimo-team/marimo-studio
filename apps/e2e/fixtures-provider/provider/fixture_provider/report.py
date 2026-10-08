"""Build one external HTML report through the public provider SPI."""

from __future__ import annotations

import sys
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    BuildInput,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInspection,
    ProviderAvailability,
    ProviderError,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    StarterContext,
    StarterPlan,
    html_sites,
)

_ENTRY = PurePosixPath("index.html")
_BUILDER = PurePosixPath("build.py")
_BUILDER_SOURCE = b"""from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
output = Path(sys.argv[2])
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(
    source.replace("</body>", '<p data-external-build="ready">Built</p></body>'),
    encoding="utf-8",
)
"""


class ReportProvider:
    info = ProviderInfo(
        title="External report",
        summary="Copies one HTML report into a browser artifact.",
    )
    _starter = ProviderStarter(
        key="default",
        title="External report",
        summary="An HTML report supplied by an installed package.",
        documents=(_ENTRY, _BUILDER),
    )

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(True, version="1.0.0")

    def starters(self) -> tuple[ProviderStarter, ...]:
        return (self._starter,)

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> StarterPlan:
        if starter != self._starter:
            raise ValueError(f"Unknown starter {starter.key!r}")
        document = f"""<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>{context.notebook_name}</title></head>
  <body>
    <main id="app-shell">
      <h1 data-external-provider>{context.view_name.replace("-", " ").title()}</h1>
      <p>Notebook value: <strong data-external-value mo-value="title"></strong></p>
    </main>
  </body>
</html>
"""
        return StarterPlan(
            files={_ENTRY: document.encode(), _BUILDER: _BUILDER_SOURCE},
            cell_targets=(),
        )

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        project = request.project
        completed = request.runner.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; assert Path('index.html').is_file()",
            ],
            cwd=project.root,
            timeout=request.command_timeout,
        )
        if completed.returncode != 0:
            raise ProviderError(completed.stderr or "External inspection failed")
        sites, diagnostics = html_sites(_ENTRY, (project.root / _ENTRY).read_bytes())
        return ProjectInspection(
            documents=(
                SourceDocument(_ENTRY, "html", "edit"),
                SourceDocument(_BUILDER, "python", "edit"),
            ),
            inputs=(
                BuildInput(_ENTRY, "file"),
                BuildInput(_BUILDER, "file"),
            ),
            sites=sites,
            diagnostics=diagnostics,
        )

    def build(self, request: BuildRequest) -> BuildResult:
        completed = request.runner.run(
            [
                sys.executable,
                _BUILDER.as_posix(),
                str(request.project.root / _ENTRY),
                str(request.staging_root / _ENTRY),
            ],
            cwd=request.project.root,
        )
        if completed.returncode != 0:
            raise ProviderError(completed.stderr or "External report build failed")
        return BuildResult(_ENTRY)


provider = ReportProvider()
