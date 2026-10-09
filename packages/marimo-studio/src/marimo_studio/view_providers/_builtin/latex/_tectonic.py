"""Compile a LaTeX entry document to PDF with Tectonic and report its problems.

Tectonic is a self-contained TeX engine. It reruns LaTeX and BibTeX until
cross-references settle, and it downloads the packages a document uses from
the bundle its version pins, so a document compiles the same way on every
machine. Studio compiles in Tectonic's untrusted mode, which turns off shell
escape, and fixes the clock at the Unix epoch so the same inputs give the same
PDF bytes. The document itself is trusted view source, and TeX reads and
writes files with the user's authority.

Errors come from Tectonic's ``error: <file>:<line>: <message>`` lines. Studio
keeps only the end of a command's output, so for a long transcript the error
comes from the LaTeX log instead, located by the source text where TeX
stopped. Undefined references and citations, and the warnings marimo.sty
writes, come from the log, and
bibliography errors from the BibTeX log. Overfull boxes wider than a point
are warnings, because a value that grows can push a line into the margin.

``marimo.sty`` logs the size it places each output at as
``marimo-size:<width>:<height>:<selector>:`` in big points, with an empty
height when the document sets none. The compile returns those sizes, widest
first, for Studio to draw each figure at.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path, PurePosixPath

from marimo_studio.view_providers import (
    BuildResult,
    ProjectDiagnostic,
    ProviderAvailability,
    ProviderError,
    ProviderRunner,
    Size,
    SourceLocation,
    probe_tool,
    project_path,
)
from marimo_studio.view_providers._builtin.latex._sources import LANGUAGES

TECTONIC_MIN_VERSION = "0.15"
INSTALL_ACTION = (
    "Install Tectonic 0.15 or newer with `pixi global install tectonic`, with "
    "`pixi add tectonic` in a pixi workspace, or from "
    "https://tectonic-typesetting.github.io/, then restart Studio."
)
_MAX_WARNINGS = 20
_MAX_MESSAGE_CHARACTERS = 2_000
# TeX breaks log lines at this many characters.
_LOG_LINE = 79
_LOCATED = re.compile(
    r"^(?P<level>error|warning): (?P<path>[^\s:][^:]*):(?P<line>\d+): ?(?P<message>.*)$"
)
_CONTINUED = re.compile(r"^(?:error|warning|note|caused by):")
_TEX_ERROR = re.compile(r"^! (?P<message>.+)$")
_CONTEXT = re.compile(r"^l\.(?P<line>\d+) (?:\.\.\.)?(?P<text>.*)$")
# TeX's help prompts and the "(package)" prefix that continues a package's
# message on the next line, which Tectonic joins into one line.
_TEX_HELP = re.compile(
    r"See the \S+ (?:package )?documentation for explanation\.|See the LaTeX manual or "
    r"LaTeX Companion for explanation\.|Type\s+H <return>\s+for immediate help\.?"
    r"|Type\s+<return>\s+to\s+continue\.?|For immediate help type H <return>\.?"
    r"|(?<=\s)\.\.\.(?=\s|$)|\s\([A-Za-z][\w-]*\)\s{2,}"
)
# Tectonic's summary lines around an engine failure, which name no cause.
_GENERIC = re.compile(
    r"^(?:something bad happened inside \S+|the \S+ engine had an unrecoverable error"
    r"|halted on potentially-recoverable error as specified)"
)
_BAD_BOX = re.compile(r"^(?:Overfull|Underfull) \\[hv]box")
_OVERFULL = re.compile(
    r"^Overfull \\[hv]box \((?P<amount>[0-9.]+)pt too (?:wide|high)\)"
)
_SIZE = re.compile(
    r"marimo-size:(?P<width>[0-9.]+):(?P<height>[0-9.]*):(?P<target>.+):$"
)
# Tectonic prints a missing character as replacement characters, followed by
# its code point, such as ("2013) or (U+2013).
_MISSING_CHARACTER = re.compile(
    r"(?P<lead>There is no )\S+ \((?:\"|U\+)(?P<hex>[0-9A-Fa-f]+)\)"
)
_UNDEFINED = re.compile(
    r"^(?:LaTeX|Package natbib) Warning: (?P<kind>Reference|Citation) `(?P<key>.*?)' "
    r"on page \S+ undefined on input line (?P<line>\d+)\.$"
)
# marimo.sty's own warnings, whose message continues on lines that start
# with "(marimo)".
_MARIMO_WARNING = re.compile(r"^Package marimo Warning: (?P<message>.*)$")
_MARIMO_CONTINUED = re.compile(r"^\(marimo\)\s+(?P<message>.*)$")
_MULTIPLY_DEFINED = re.compile(
    r"^LaTeX Warning: Label `(?P<key>.*?)' multiply defined\.$"
)
_BIBTEX_ERROR = re.compile(
    r"^(?P<message>.+?)---(?:line (?P<line>\d+) of file|while reading file) "
    r"(?P<path>\S+)$"
)


def tectonic_availability() -> ProviderAvailability:
    """Report whether a supported Tectonic can run."""
    return probe_tool(
        ("tectonic", "--version"),
        minimum=TECTONIC_MIN_VERSION,
        install=INSTALL_ACTION,
    )


class _Sources:
    """Resolve the file names Tectonic reports to the project's Source documents."""

    def __init__(self, root: Path, entry: PurePosixPath) -> None:
        self.root = root
        self.base = entry.parent

    def resolve(self, name: str) -> PurePosixPath | None:
        """Return the Source document TeX names, if Source shows it.

        TeX reports a file as the document named it, relative to the entry
        document and sometimes without its ``.tex`` suffix. Other files, such
        as Studio's render inputs or a TikZ picture, resolve to nothing.
        """
        for candidate in (name, f"{name}.tex"):
            try:
                path = project_path(PurePosixPath(self.base, candidate).as_posix())
            except ValueError:
                return None
            if (
                path.suffix.lower() in LANGUAGES
                and not any(part.startswith(".") for part in path.parts)
                and self.root.joinpath(*path.parts).is_file()
            ):
                return path
        return None

    def locate(self, text: str, line: int) -> SourceLocation | None:
        """Return where one LaTeX source has ``text`` on ``line``, if only one does."""
        found: list[SourceLocation] = []
        for path in sorted(self.root.rglob("*")):
            relative = PurePosixPath(path.relative_to(self.root).as_posix())
            # Hidden directories hold Studio's render inputs, not the document.
            if path.suffix.lower() not in {".tex", ".sty", ".cls"} or any(
                part.startswith(".") for part in relative.parts
            ):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            if line <= len(lines) and (column := lines[line - 1].find(text)) >= 0:
                found.append(SourceLocation(relative, line, column + 1))
        return found[0] if len(found) == 1 else None

    def location(self, name: str, line: int) -> tuple[SourceLocation | None, str]:
        """Return a source location, or the prefix that names a file outside it."""
        path = self.resolve(name)
        if path is None:
            return None, f"{name}:{line}: "
        return SourceLocation(path, line, 1), ""


def _report(
    stderr: str,
) -> tuple[list[tuple[str, str, int, str]], list[str], str | None]:
    """Split Tectonic's report into located messages, others, and TeX's context.

    Returns ``(level, file, line, message)`` items, the unlocated error and
    cause lines, and the source text where TeX stopped, if it printed one.
    """
    located: list[tuple[str, str, int, str]] = []
    unlocated: list[str] = []
    context: str | None = None
    lines = stderr.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        match = _LOCATED.match(line)
        if match is not None:
            message = [match["message"].removeprefix("! ").strip()]
            while index < len(lines) and not _CONTINUED.match(lines[index]):
                message.append(lines[index].strip())
                index += 1
            located.append(
                (match["level"], match["path"], int(match["line"]), _plain(message))
            )
            continue
        if context is None and (found := _CONTEXT.match(line)) is not None:
            context = found["text"].strip() or None
        elif line.startswith(("error: ", "caused by: ")):
            unlocated.append(line.split(": ", 1)[1].strip())
    return located, unlocated, context


def _plain(message: list[str]) -> str:
    """Return a TeX message on one line, without its help prompts."""
    return " ".join(_TEX_HELP.sub(" ", " ".join(message)).split())


def _log_lines(log: str) -> list[str]:
    """Return the log's lines with TeX's line breaks joined back."""
    joined: list[str] = []
    carry = ""
    for line in log.splitlines():
        carry += line
        if len(line) != _LOG_LINE:
            joined.append(carry)
            carry = ""
    if carry:
        joined.append(carry)
    return joined


def _log_error(log: str) -> tuple[str, int | None, str | None] | None:
    """Return the first TeX error in the log, its input line, and the text read.

    The message runs to the first blank line, before TeX's prompts.
    """
    lines = _log_lines(log)
    for index, line in enumerate(lines):
        if (error := _TEX_ERROR.match(line)) is None:
            continue
        message = [error["message"]]
        for follow in lines[index + 1 :]:
            if not follow.strip() or _CONTEXT.match(follow):
                break
            message.append(follow)
        for follow in lines[index + 1 : index + 16]:
            if (context := _CONTEXT.match(follow)) is not None:
                text = context["text"].strip()
                return _plain(message), int(context["line"]), text or None
        return _plain(message), None, None
    return None


def _bounded(message: str) -> str:
    return message[:_MAX_MESSAGE_CHARACTERS].strip()


def _stopped(message: str, context: str | None) -> str:
    stopped = f' TeX stopped after "{context}".' if context else ""
    return f"{message.rstrip('.')}.{stopped}"


def _failure(
    stderr: str,
    log: str,
    sources: _Sources,
    entry: PurePosixPath,
) -> ProjectDiagnostic:
    located, unlocated, context = _report(stderr)
    errors = [item for item in located if item[0] == "error"]
    if errors:
        _level, name, line, message = errors[0]
        source, prefix = sources.location(name, line)
        return ProjectDiagnostic(
            "latex-compile-error",
            "error",
            _bounded(prefix + _stopped(message, context)),
            f"Fix {source.path if source else entry}, then save it to render again.",
            source,
        )
    # TeX writes no pages for a document without content, and xdvipdfmx then
    # reports only that its input is missing.
    if "No pages of output." in stderr or "No pages of output." in log:
        return ProjectDiagnostic(
            "latex-compile-error",
            "error",
            f"{entry} typeset no pages.",
            "Typeset content between \\begin{document} and \\end{document}.",
            SourceLocation(entry, 1, 1),
        )
    if (logged := _log_error(log)) is not None:
        message, line, text = logged
        source = sources.locate(text, line) if text and line else None
        return ProjectDiagnostic(
            "latex-compile-error",
            "error",
            _bounded(_stopped(message, text)),
            f"Fix {source.path if source else entry}, then save it to render again.",
            source,
        )
    # Without a TeX error, the most specific lines are the causes, such as an
    # image that xdvipdfmx could not read.
    specific = [item for item in unlocated if not _GENERIC.match(item)]
    message = " ".join(specific) or stderr.strip()[-_MAX_MESSAGE_CHARACTERS:]
    return ProjectDiagnostic(
        "latex-compile-error",
        "error",
        _bounded(message or f"Tectonic could not compile {entry}."),
        f"Fix {entry}, then save it to render again.",
        SourceLocation(entry, 1, 1),
    )


def _warning(message: str, source: SourceLocation | None) -> ProjectDiagnostic:
    return ProjectDiagnostic(
        "latex-compile-warning",
        "warning",
        _bounded(message),
        source=source,
    )


def _readable(message: str) -> str:
    """Return a warning that shows each missing character as itself."""
    return _MISSING_CHARACTER.sub(
        lambda match: (
            f"{match['lead']}{chr(int(match['hex'], 16))} (U+{match['hex'].upper()})"
        ),
        message,
    )


def _warnings(
    stderr: str,
    log: str,
    bibtex: str,
    sources: _Sources,
) -> tuple[ProjectDiagnostic, ...]:
    found: list[ProjectDiagnostic] = []
    located, _unlocated, _context = _report(stderr)
    for level, name, line, message in located:
        if level != "warning" or not message:
            continue
        overfull = _OVERFULL.match(message)
        if _BAD_BOX.match(message) and (
            overfull is None or float(overfull["amount"]) <= 1
        ):
            continue
        source, prefix = sources.location(name, line)
        found.append(_warning(f"{prefix}{_readable(message)}", source))
    lines = _log_lines(log)
    for index, line in enumerate(lines):
        if (match := _MARIMO_WARNING.match(line)) is not None:
            message = [match["message"]]
            for follow in lines[index + 1 :]:
                if (continued := _MARIMO_CONTINUED.match(follow)) is None:
                    break
                message.append(continued["message"])
            found.append(_warning(" ".join(" ".join(message).split()), None))
        elif (match := _UNDEFINED.match(line)) is not None:
            kind, key = match["kind"], match["key"]
            found.append(
                _warning(
                    f"{kind} `{key}` is undefined.",
                    sources.locate(key, int(match["line"])),
                )
            )
        elif (match := _MULTIPLY_DEFINED.match(line)) is not None:
            found.append(
                _warning(f"Label `{match['key']}` is defined more than once.", None)
            )
    # BibTeX prints some error locations on the line after the message.
    for line in re.sub(r"\n(?=---)", "", bibtex).splitlines():
        if (match := _BIBTEX_ERROR.match(line.strip())) is not None:
            path = sources.resolve(match["path"])
            source = (
                SourceLocation(path, int(match["line"]), 1)
                if path is not None and match["line"] and path.suffix == ".bib"
                else None
            )
            found.append(_warning(f"BibTeX: {match['message']}", source))
    unique = list(dict.fromkeys(found))
    return tuple(unique[:_MAX_WARNINGS])


def _output_sizes(log: str) -> dict[str, Size]:
    """Return the widest size the document places each output at."""
    sizes: dict[str, Size] = {}
    for line in _log_lines(log):
        # A record that follows a line TeX broke at exactly its limit joins
        # that line, so it is read from the end of the joined line.
        if (match := _SIZE.search(line)) is None:
            continue
        try:
            size = Size(
                float(match["width"]),
                float(match["height"]) if match["height"] else None,
            )
        except ValueError:
            # A slot without width, or one wider than a figure can be drawn,
            # places the output at the size the notebook drew it.
            continue
        target = match["target"]
        if target not in sizes or size.width > sizes[target].width:
            sizes[target] = size
    return sizes


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def compile_latex(
    runner: ProviderRunner,
    root: Path,
    entry: PurePosixPath,
    output: Path,
    timeout: float,
) -> BuildResult:
    """Compile ``entry`` beneath ``root`` into ``output`` and return the PDF.

    Tectonic writes the PDF and its logs into ``output``. Relative paths in the
    document resolve from the entry document's directory.
    """
    binary = shutil.which("tectonic")
    if binary is None:
        raise ProviderError(
            "Studio cannot find the tectonic command.", hint=INSTALL_ACTION
        )
    output.mkdir(parents=True, exist_ok=True)
    completed = runner.run(
        [
            binary,
            "-X",
            "compile",
            "--untrusted",
            "--keep-logs",
            "--outdir",
            str(output),
            "--",
            entry.name,
        ],
        cwd=root.joinpath(*entry.parent.parts),
        timeout=timeout,
        environment={**os.environ, "SOURCE_DATE_EPOCH": "0"},
    )
    sources = _Sources(root, entry)
    pdf = output / f"{entry.stem}.pdf"
    log = _read(output / f"{entry.stem}.log")
    if completed.returncode != 0 or not pdf.is_file():
        return BuildResult(None, (_failure(completed.stderr, log, sources, entry),))
    return BuildResult(
        PurePosixPath(pdf.name),
        _warnings(
            completed.stderr,
            log,
            _read(output / f"{entry.stem}.blg"),
            sources,
        ),
        _output_sizes(log),
    )
