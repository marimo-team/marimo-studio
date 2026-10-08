"""Locate the Quarto CLI and render one inspected document to HTML."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
from html.parser import HTMLParser
from importlib import resources
from pathlib import Path, PurePosixPath

from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    ProjectDiagnostic,
    ProviderAvailability,
    ProviderError,
    SourceLocation,
    copy_inputs,
    probe_tool,
)

QUARTO_MIN_VERSION = "1.9.38"
INSTALL_ACTION = (
    "Install Quarto 1.9.38 or newer from https://quarto.org/docs/get-started/, "
    "or with `pixi global install quarto`, then restart Studio."
)
ACTIVATE_ACTION = (
    "Activate the environment that provides Quarto, for example with "
    "`pixi shell` or `conda activate <environment>`, then restart Studio."
)
_ERROR_LINE = re.compile(r"^\s*ERROR:\s*(.+)$", re.MULTILINE)
_MAX_REPORT_CHARACTERS = 2_000


def _conda_quarto(executable: Path) -> bool:
    """Return whether the conda-forge quarto package installed an executable."""
    # Executables live in <prefix>/bin, or in <prefix>/Library/bin on Windows.
    for prefix in (executable.parent.parent, executable.parent.parent.parent):
        if any((prefix / "conda-meta").glob("quarto-[0-9]*.json")):
            return True
    return False


def quarto_availability() -> ProviderAvailability:
    """Report whether a supported Quarto CLI can run."""
    found = shutil.which("quarto")
    # conda-forge Quarto finds Pandoc, Deno, and its resources through
    # variables that environment activation sets.
    if (
        found is not None
        and _conda_quarto(Path(found))
        and "QUARTO_SHARE_PATH" not in os.environ
    ):
        return ProviderAvailability(
            False,
            reason=(
                "Studio found Quarto in a pixi or conda environment that is not "
                "activated."
            ),
            action=ACTIVATE_ACTION,
        )
    return probe_tool(
        ("quarto", "--version"),
        minimum=QUARTO_MIN_VERSION,
        install=INSTALL_ACTION,
    )


class _BodyBounds(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self._line_starts = [0]
        for line in source.split("\n"):
            self._line_starts.append(self._line_starts[-1] + len(line) + 1)
        self.body_open_end: int | None = None
        self.body_close: int | None = None
        self.has_shell = False

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if dict(attrs).get("id") == "app-shell":
            self.has_shell = True
        if tag == "body" and self.body_open_end is None:
            self.body_open_end = self._offset() + len(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "body":
            self.body_close = self._offset()


def _with_app_shell(content: bytes, entry: PurePosixPath) -> str:
    source = SourceLocation(entry, 1, 1)
    try:
        document = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProviderError(
            "Quarto produced HTML that is not UTF-8.",
            source=source,
            code="quarto-output-invalid",
        ) from error
    bounds = _BodyBounds(document)
    bounds.feed(document)
    bounds.close()
    if bounds.has_shell:
        raise ProviderError(
            "Studio reserves id app-shell for the element that wraps the page.",
            hint="Remove id app-shell from the document source.",
            source=source,
            code="quarto-output-invalid",
        )
    if bounds.body_open_end is None or bounds.body_close is None:
        raise ProviderError(
            "Quarto produced HTML without <body> and </body>.",
            source=source,
            code="quarto-output-invalid",
        )
    start, end = bounds.body_open_end, bounds.body_close
    return (
        f'{document[:start]}<div id="app-shell">{document[start:end]}</div>'
        f"{document[end:]}"
    )


def _failure(entry: PurePosixPath, stderr: str) -> ProjectDiagnostic:
    # The message starts at Quarto's first error and keeps the context after it.
    report = stderr.split("Stack trace:", 1)[0]
    error = _ERROR_LINE.search(report)
    message = (
        (error[1] + report[error.end() :]).strip()[:_MAX_REPORT_CHARACTERS].strip()
        if error is not None
        else f"Quarto could not render {entry.as_posix()}."
    )
    return ProjectDiagnostic(
        code="quarto-render-failed",
        severity="error",
        message=message,
        hint=f"Fix {entry.as_posix()}, then save it to render again.",
        source=SourceLocation(entry, 1, 1),
    )


def _render_environment(cache_root: Path, binary: str) -> dict[str, str]:
    """Return the environment for one Quarto render.

    Quarto shares one user cache across installations, and a Quarto that runs
    on another Deno fails to read entries a different one wrote
    (``RangeError: could not deserialize value``). Each Quarto installation
    gets its own cache beneath ``cache_root``. Quarto locates the cache from
    HOME on macOS, XDG_CACHE_HOME on Linux, and LOCALAPPDATA on Windows.
    """
    installation = f"{Path(binary).resolve()}\0{quarto_availability().version}"
    home = (
        cache_root / "quarto" / hashlib.sha256(installation.encode()).hexdigest()[:16]
    )
    environment = {**os.environ, "NO_COLOR": "1"}
    if sys.platform == "darwin":
        environment["HOME"] = str(home)
    elif os.name == "nt":
        environment["LOCALAPPDATA"] = str(home)
    else:
        environment["XDG_CACHE_HOME"] = str(home)
    return environment


def _install_extension(work: Path, entry: PurePosixPath) -> None:
    """Place the marimo shortcode extension where Quarto finds it for the entry.

    Quarto discovers extensions in an ``_extensions`` directory beside the
    rendered document. The copy lives in the private working directory, so the
    authored project stays unchanged and always renders with this Studio's
    shortcode.
    """
    target = work.joinpath(*entry.parent.parts, "_extensions", "marimo-studio")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    extension = resources.files(__package__ or __name__).joinpath("_extension")
    for name in ("_extension.yml", "marimo.lua"):
        target.joinpath(name).write_bytes(extension.joinpath(name).read_bytes())


def build_quarto(request: BuildRequest, entry: PurePosixPath) -> BuildResult:
    """Render the snapshot entry to HTML beneath the staging root."""
    work = request.work_root
    copy_inputs(request, work)
    _install_extension(work, entry)
    binary = shutil.which("quarto")
    if binary is None:
        raise ProviderError(
            "Studio cannot find the quarto command.", hint=INSTALL_ACTION
        )
    hosts_filter = resources.files(__package__ or __name__).joinpath("marimo-hosts.lua")
    with resources.as_file(hosts_filter) as filter_path:
        completed = request.runner.run(
            [
                binary,
                "render",
                entry.as_posix(),
                "--to",
                "html",
                "--no-execute",
                "--output-dir",
                str(request.staging_root),
                "--lua-filter",
                str(filter_path),
            ],
            cwd=work,
            timeout=request.command_timeout,
            environment=_render_environment(request.cache_root, binary),
        )
    if completed.returncode != 0:
        return BuildResult(None, (_failure(entry, completed.stderr),))
    document = entry.with_suffix(".html")
    output = request.staging_root.joinpath(*document.parts)
    if not output.is_file():
        output = request.staging_root / document.name
        document = PurePosixPath(document.name)
    if not output.is_file():
        return BuildResult(
            None,
            (_failure(entry, f"ERROR: Quarto wrote no {document.as_posix()}."),),
        )
    output.write_bytes(_with_app_shell(output.read_bytes(), entry).encode("utf-8"))
    return BuildResult(document)
