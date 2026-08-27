"""Scan CSS once for URLs fetched outside a single HTML document."""

from __future__ import annotations


def _consume_escape(source: str, index: int) -> tuple[str, int]:
    if index >= len(source):
        return "", index
    if source[index] in "\n\r\f":
        if source[index] == "\r" and source[index : index + 2] == "\r\n":
            return "", index + 2
        return "", index + 1
    end = index
    while (
        end < len(source)
        and end - index < 6
        and source[end] in "0123456789abcdefABCDEF"
    ):
        end += 1
    if end != index:
        codepoint = int(source[index:end], 16)
        if end < len(source) and source[end].isspace():
            end += 1
        if codepoint == 0 or 0xD800 <= codepoint <= 0xDFFF or codepoint > 0x10FFFF:
            return "\N{REPLACEMENT CHARACTER}", end
        return chr(codepoint), end
    return source[index], index + 1


def _consume_token(
    source: str,
    index: int,
    *,
    quote: str | None = None,
) -> tuple[str, int]:
    value: list[str] = []
    while index < len(source):
        character = source[index]
        if quote is not None and character == quote:
            return "".join(value), index + 1
        if quote is None and (character == ")" or character.isspace()):
            return "".join(value), index
        if character == "\\":
            escaped, index = _consume_escape(source, index + 1)
            value.append(escaped)
            continue
        value.append(character)
        index += 1
    return "".join(value), index


def _skip_space(source: str, index: int) -> int:
    while index < len(source):
        if source[index].isspace():
            index += 1
            continue
        if source.startswith("/*", index):
            close = source.find("*/", index + 2)
            if close < 0:
                return len(source)
            index = close + 2
            continue
        return index
    return index


def _consume_identifier(source: str, index: int) -> tuple[str, int]:
    value: list[str] = []
    while index < len(source):
        character = source[index]
        if character.isalnum() or character in "_-" or ord(character) >= 0x80:
            value.append(character)
            index += 1
            continue
        if character == "\\":
            escaped, index = _consume_escape(source, index + 1)
            value.append(escaped)
            continue
        break
    return "".join(value), index


def css_resource_urls(source: str) -> tuple[tuple[str, int], ...]:
    """Return fetched CSS resource URLs and their source offsets."""
    resources: list[tuple[str, int]] = []
    functions: list[bool] = []
    index = 0
    import_value_expected = False
    while index < len(source):
        if source.startswith("/*", index):
            index = _skip_space(source, index)
            continue
        character = source[index]
        if character in "\"'":
            value_offset = index
            value, index = _consume_token(source, index + 1, quote=character)
            if import_value_expected or (functions and functions[-1]):
                resources.append((value, value_offset))
            import_value_expected = False
            continue
        if character == "@":
            identifier, end = _consume_identifier(source, index + 1)
            import_value_expected = identifier.casefold() == "import"
            index = _skip_space(source, end)
            continue
        if character.isalpha() or character in "_-\\" or ord(character) >= 0x80:
            identifier, end = _consume_identifier(source, index)
            opening = _skip_space(source, end)
            function = opening < len(source) and source[opening] == "("
            normalized = identifier.casefold()
            if normalized != "url" or not function:
                import_value_expected = False
                if function:
                    functions.append(normalized in {"image-set", "-webkit-image-set"})
                    index = opening + 1
                else:
                    index = end
                continue
            value_offset = _skip_space(source, opening + 1)
            if value_offset < len(source) and source[value_offset] in "\"'":
                value, end = _consume_token(
                    source,
                    value_offset + 1,
                    quote=source[value_offset],
                )
            else:
                value, end = _consume_token(source, value_offset)
            resources.append((value.strip(), value_offset))
            import_value_expected = False
            close = _skip_space(source, end)
            index = close + 1 if close < len(source) and source[close] == ")" else end
            continue
        if character == "(":
            functions.append(False)
        elif character == ")" and functions:
            functions.pop()
        if not character.isspace():
            import_value_expected = False
        index += 1
    return tuple(resources)
