"""Write one render's notebook values, outputs, and cells as LaTeX definitions.

``marimo.sty`` reads ``.marimo-studio/inputs.tex`` beside the entry document.
Its first line names the format version, and each further line defines one
read with its type:

.. code-block:: latex

    \\marimo@inputs{2}
    \\marimo@s{scope.label}{Weekdays \\textperiodcentered{} 07:00}
    \\marimo@n{model.accuracy}{0.9884}
    \\marimo@b{model.final}{1}
    \\marimo@z{peak}
    \\marimo@l{days}{7}
    \\marimo@d{days[0]}{3}
    \\marimo@s{days[0].day}{2015-02-04}
    \\marimo@t{days[0].day}{2015-02-04}{}
    \\marimo@g{figure}{.marimo-studio/outputs/<sha256>.pdf}
    \\marimo@c{plot}{.marimo-studio/outputs/<sha256>.png}
    \\marimo@u{summary.total}

Every item inside a value is defined under its selector, so a row of
``\\marimorows`` reads its fields, such as ``days[0].day``. Text that holds an
ISO 8601 date, datetime, or time also defines its date and time parts with
``\\marimo@t`` for ``\\marimodate`` and ``\\marimotime``. A read the document
makes that the render does not supply is unavailable, ``\\marimo@u``, or for a
cell an empty path. Strings become text that typesets the same in T1 and
Unicode fonts: TeX's special characters are escaped, and other characters use
LaTeX's encoding-independent commands, such as ``\\textdegree{}`` and
``\\'{e}``. Unlisted characters pass through unchanged and need a font that
has them.
"""

from __future__ import annotations

import datetime
import json
import re
import unicodedata
from collections.abc import Iterator, Mapping

from marimo_export.wire import canonical_json_bytes

from marimo_studio.view_providers import JsonValue
from marimo_studio.view_providers._builtin._typeset import DocumentReads

INPUTS_VERSION = 2
# A document reads a value to place a few of its fields, so values that need
# more definitions than this hold a table or dataset the notebook should
# project first. TeX holds this many in well under a second.
MAX_INPUT_DEFINITIONS = 60_000

_SPECIALS = {
    '"': r"\textquotedbl{}",
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "#": r"\#",
    "$": r"\$",
    "%": r"\%",
    "&": r"\&",
    "_": r"\_",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
    "|": r"\textbar{}",
}


def _math(command: str, character: str) -> str:
    """Return a math symbol that PDF strings, such as bookmarks, keep."""
    return f"\\texorpdfstring{{\\ensuremath{{{command}}}}}{{{character}}}"


_SYMBOLS = {
    "\u00a0": "~",
    "\u00a1": r"\textexclamdown{}",
    "\u00a2": r"\textcent{}",
    "\u00a3": r"\pounds{}",
    "\u00a4": r"\textcurrency{}",
    "\u00a5": r"\textyen{}",
    "\u00a6": r"\textbrokenbar{}",
    "\u00a7": r"\S{}",
    "\u00a8": r"\textasciidieresis{}",
    "\u00a9": r"\textcopyright{}",
    "\u00aa": r"\textordfeminine{}",
    "\u00ab": r"\guillemotleft{}",
    "\u00ac": r"\textlnot{}",
    "\u00ad": r"\-",
    "\u00ae": r"\textregistered{}",
    "\u00af": r"\textasciimacron{}",
    "\u00b0": r"\textdegree{}",
    "\u00b4": r"\textasciiacute{}",
    "\u00b1": r"\textpm{}",
    "\u00b5": r"\textmu{}",
    "\u00b6": r"\P{}",
    "\u00b7": r"\textperiodcentered{}",
    "\u00b8": r"\c{}",
    "\u00ba": r"\textordmasculine{}",
    "\u00bb": r"\guillemotright{}",
    "\u00bc": r"\textonequarter{}",
    "\u00bd": r"\textonehalf{}",
    "\u00be": r"\textthreequarters{}",
    "\u00bf": r"\textquestiondown{}",
    "\u00c6": r"\AE{}",
    "\u00d0": r"\DH{}",
    "\u00d7": r"\texttimes{}",
    "\u00d8": r"\O{}",
    "\u00de": r"\TH{}",
    "\u00df": r"\ss{}",
    "\u00e6": r"\ae{}",
    "\u00f0": r"\dh{}",
    "\u00f7": r"\textdiv{}",
    "\u00f8": r"\o{}",
    "\u00fe": r"\th{}",
    "\u0110": r"\DJ{}",
    "\u0111": r"\dj{}",
    "\u0131": r"\i{}",
    "\u0141": r"\L{}",
    "\u0142": r"\l{}",
    "\u0152": r"\OE{}",
    "\u0153": r"\oe{}",
    "\u2009": r"\,",
    "\u2013": r"\textendash{}",
    "\u2014": r"\textemdash{}",
    "\u2018": r"\textquoteleft{}",
    "\u2019": r"\textquoteright{}",
    "\u201a": r"\quotesinglbase{}",
    "\u201c": r"\textquotedblleft{}",
    "\u201d": r"\textquotedblright{}",
    "\u201e": r"\quotedblbase{}",
    "\u2020": r"\textdagger{}",
    "\u2021": r"\textdaggerdbl{}",
    "\u2022": r"\textbullet{}",
    "\u2026": r"\textellipsis{}",
    "\u202f": r"\,",
    "\u2030": r"\textperthousand{}",
    "\u2032": _math("{}^{\\prime}", "\u2032"),
    "\u2039": r"\guilsinglleft{}",
    "\u203a": r"\guilsinglright{}",
    "\u20ac": r"\texteuro{}",
    "\u2122": r"\texttrademark{}",
    "\u2190": r"\textleftarrow{}",
    "\u2191": r"\textuparrow{}",
    "\u2192": r"\textrightarrow{}",
    "\u2193": r"\textdownarrow{}",
    "\u2212": r"\textminus{}",
    "\u221e": _math("\\infty", "\u221e"),
    "\u2248": _math("\\approx", "\u2248"),
    "\u2260": _math("\\neq", "\u2260"),
    "\u2264": _math("\\leq", "\u2264"),
    "\u2265": _math("\\geq", "\u2265"),
}
_GREEK = {
    "\u0393": "Gamma",
    "\u0394": "Delta",
    "\u0398": "Theta",
    "\u039b": "Lambda",
    "\u039e": "Xi",
    "\u03a0": "Pi",
    "\u03a3": "Sigma",
    "\u03a5": "Upsilon",
    "\u03a6": "Phi",
    "\u03a8": "Psi",
    "\u03a9": "Omega",
    "\u03b1": "alpha",
    "\u03b2": "beta",
    "\u03b3": "gamma",
    "\u03b4": "delta",
    "\u03b5": "epsilon",
    "\u03b6": "zeta",
    "\u03b7": "eta",
    "\u03b8": "theta",
    "\u03b9": "iota",
    "\u03ba": "kappa",
    "\u03bb": "lambda",
    "\u03bc": "mu",
    "\u03bd": "nu",
    "\u03be": "xi",
    "\u03c0": "pi",
    "\u03c1": "rho",
    "\u03c3": "sigma",
    "\u03c4": "tau",
    "\u03c5": "upsilon",
    "\u03c6": "phi",
    "\u03c7": "chi",
    "\u03c8": "psi",
    "\u03c9": "omega",
}
_SYMBOLS.update({letter: _math(f"\\{name}", letter) for letter, name in _GREEK.items()})
_SYMBOLS.update(
    {chr(0x2080 + digit): rf"\textsubscript{{{digit}}}" for digit in range(10)}
)
_SYMBOLS.update(
    {
        character: rf"\textsuperscript{{{digit}}}"
        for digit, character in enumerate(
            "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079"
        )
    }
)
_ACCENTS = {
    "\u0300": "`",
    "\u0301": "'",
    "\u0302": "^",
    "\u0303": "~",
    "\u0304": "=",
    "\u0306": "u",
    "\u0307": ".",
    "\u0308": '"',
    "\u030a": "r",
    "\u030b": "H",
    "\u030c": "v",
    "\u0323": "d",
    "\u0327": "c",
    "\u0328": "k",
    "\u0326": "textcommabelow",
    "\u0331": "b",
}
_WRAP_AT = 1_000
_WRAP_LIMIT = 4_000
# Character pairs that TeX fonts join into another glyph, such as -- into an
# en dash. Text from the notebook keeps them apart.
_LIGATURES = frozenset({"--", "''", "``", ",,", "!`", "?`"})
# Selector attribute steps name public attributes, so a key that starts with _
# is read as an item, such as rows["_id"].
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_CONTROL_WORD = re.compile(r"\\[A-Za-z]+")
# A dictionary key can only be addressed from LaTeX source when TeX reads it
# back as the same characters.
_UNADDRESSABLE = re.compile(r'[\\{}%#^"\x00-\x1f\x7f]')


class InputsTooLarge(ValueError):
    """The values a render reads need more than ``MAX_INPUT_DEFINITIONS``."""


def _accented(character: str) -> str | None:
    """Return a precomposed letter as LaTeX accent commands, such as ``\\'{e}``."""
    base, *marks = unicodedata.normalize("NFD", character)
    if not marks or not base.isascii() or not base.isalpha():
        return None
    text = base
    for mark in marks:
        accent = _ACCENTS.get(mark)
        if accent is None:
            return None
        text = f"\\{accent}{{{text}}}"
    return text


def latex_text(value: str) -> str:
    """Return ``value`` as LaTeX text that typesets those characters.

    A command such as ``\\textdegree`` ends with a space before a character
    and with ``{}`` before a space or the end, so it also reads cleanly where
    hyperref turns the text into a link. Format characters, such as a zero
    width space, are dropped.

    TeX reads a source line of at most 200,000 characters, so long text wraps.
    A line ends at a space once it passes ``_WRAP_AT`` characters, and TeX
    reads that line end as the space. A run without spaces ends its line with
    ``%`` at ``_WRAP_LIMIT`` characters, which joins the lines.
    """
    characters: list[str] = []
    for character in unicodedata.normalize("NFC", value):
        category = unicodedata.category(character)
        if character in "\n\r\t" or category in {"Zl", "Zp"}:
            characters.append(" ")
        elif category not in {"Cc", "Cf"}:
            characters.append(character)
    parts: list[str] = []
    previous = ""
    line = 0
    for index, character in enumerate(characters):
        if character == " " and line >= _WRAP_AT:
            parts.append("\n")
            previous, line = character, 0
            continue
        if line >= _WRAP_LIMIT:
            parts.append("%\n")
            line = 0
        if previous + character in _LIGATURES:
            parts.append("{}")
            line += 2
        previous = character
        if character in _SPECIALS:
            text = _SPECIALS[character]
        elif character.isascii():
            text = character
        elif character in _SYMBOLS:
            text = _SYMBOLS[character]
        else:
            text = _accented(character) or character
        following = characters[index + 1] if index + 1 < len(characters) else " "
        if (
            text.endswith("{}")
            and _CONTROL_WORD.fullmatch(text[:-2])
            and following != " "
        ):
            text = f"{text[:-2]} "
        parts.append(text)
        line += len(text)
    return "".join(parts)


def _member(selector: str, key: str) -> str | None:
    if _IDENTIFIER.fullmatch(key):
        return f"{selector}.{key}"
    if _UNADDRESSABLE.search(key):
        return None
    return f"{selector}[{json.dumps(key, ensure_ascii=False)}]"


# ISO 8601 text as the notebook's dates, datetimes, and times arrive.
_MOMENT = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})?"
    r"(?:(?(date)[T ])(?P<time>\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)"
    r"(?:Z|[+-]\d{2}:\d{2})?)?"
)


def _moment(text: str) -> tuple[str, str] | None:
    """Return the date and time parts of ISO 8601 text, or ``None``."""
    match = _MOMENT.fullmatch(text)
    if match is None or not (match["date"] or match["time"]):
        return None
    try:
        day = datetime.date.fromisoformat(match["date"]) if match["date"] else None
        moment = datetime.time.fromisoformat(match["time"]) if match["time"] else None
    except ValueError:
        return None
    return (
        day.isoformat() if day else "",
        moment.replace(microsecond=0).isoformat() if moment else "",
    )


def _definitions(selector: str, value: JsonValue) -> Iterator[str]:
    if value is None:
        yield f"\\marimo@z{{{selector}}}"
    elif isinstance(value, bool):
        yield f"\\marimo@b{{{selector}}}{{{int(value)}}}"
    elif isinstance(value, (int, float)):
        number = canonical_json_bytes(value, selector).decode()
        yield f"\\marimo@n{{{selector}}}{{{number}}}"
    elif isinstance(value, str):
        yield f"\\marimo@s{{{selector}}}{{{latex_text(value)}}}"
        if (parts := _moment(value)) is not None:
            yield f"\\marimo@t{{{selector}}}{{{parts[0]}}}{{{parts[1]}}}"
    elif isinstance(value, list):
        yield f"\\marimo@l{{{selector}}}{{{len(value)}}}"
        for index, item in enumerate(value):
            yield from _definitions(f"{selector}[{index}]", item)
    else:
        yield f"\\marimo@d{{{selector}}}{{{len(value)}}}"
        for key, item in value.items():
            member = _member(selector, key)
            if member is not None:
                yield from _definitions(member, item)


def render_inputs(
    values: Mapping[str, JsonValue],
    outputs: Mapping[str, str],
    cells: Mapping[str, str],
    reads: DocumentReads,
) -> str:
    """Return the inputs file that defines one render's reads.

    ``outputs`` and ``cells`` map each target to its image path relative to the
    entry document. Each target in ``reads`` the render does not supply is
    unavailable. Raises ``InputsTooLarge`` when the values need more than
    ``MAX_INPUT_DEFINITIONS`` definitions.
    """
    # Unavailable reads come first, so a field that a supplied value defines,
    # such as rows[0].label inside rows, keeps its value.
    unavailable = {
        *(read.target for read in reads.values if read.target not in values),
        *(read.target for read in reads.outputs if read.target not in outputs),
    }
    lines = [f"\\marimo@inputs{{{INPUTS_VERSION}}}"]
    lines.extend(f"\\marimo@u{{{target}}}" for target in sorted(unavailable))
    lines.extend(
        f"\\marimo@c{{{name}}}{{}}"
        for name in sorted({read.target for read in reads.cells} - set(cells))
    )
    for target, value in sorted(values.items()):
        for line in _definitions(target, value):
            lines.append(line)
            if len(lines) > MAX_INPUT_DEFINITIONS:
                raise InputsTooLarge
    lines.extend(
        f"\\marimo@g{{{target}}}{{{path}}}" for target, path in sorted(outputs.items())
    )
    lines.extend(
        f"\\marimo@c{{{name}}}{{{path}}}" for name, path in sorted(cells.items())
    )
    return "\n".join(lines) + "\n"
