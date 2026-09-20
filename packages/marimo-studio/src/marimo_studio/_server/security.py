"""Validate and represent Studio server security policy."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from ipaddress import IPv6Address, ip_address
from urllib.parse import urlsplit

from marimo_studio.errors import ConfigurationError

ALLOWED_EMBED_ORIGINS_ENV = "MARIMO_STUDIO_ALLOWED_EMBED_ORIGINS"
_ALLOWED_EMBED_ORIGINS_MAX_BYTES = 4096
_ALLOWED_EMBED_ORIGINS_MAX_ENTRIES = 32
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.IGNORECASE)


@dataclass(frozen=True)
class Origin:
    value: str


@dataclass(frozen=True)
class SecurityPolicy:
    allowed_embed_origins: tuple[Origin, ...] = ()


DEFAULT_SECURITY_POLICY = SecurityPolicy()


class _HostParentOriginParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.origins: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() != "script":
            return
        origin = dict(attrs).get("data-parent-origin")
        if origin is not None:
            self.origins.append(origin)


def parse_allowed_embed_origins(value: str) -> SecurityPolicy:
    """Return a security policy from the configured comma-separated origins."""
    raw_origins = () if value == "" else tuple(value.split(","))
    return _security_policy(
        raw_origins,
        encoded=value,
    )


def extend_security_policy_from_host_head(
    policy: SecurityPolicy,
    html_head: str | None,
) -> SecurityPolicy:
    """Include bounded parent origins declared by trusted host scripts."""
    if not html_head:
        return policy
    parser = _HostParentOriginParser()
    parser.feed(html_head)
    origins = list(policy.allowed_embed_origins)
    seen = {origin.value for origin in origins}
    encoded_bytes = sum(len(origin.value.encode("utf-8")) for origin in origins)
    encoded_bytes += max(0, len(origins) - 1)
    for raw_origin in parser.origins:
        try:
            origin = _canonical_origin(raw_origin)
        except (UnicodeError, ValueError):
            continue
        if origin.value in seen:
            continue
        separator_bytes = 1 if origins else 0
        candidate_bytes = (
            encoded_bytes + separator_bytes + len(origin.value.encode("utf-8"))
        )
        if (
            len(origins) >= _ALLOWED_EMBED_ORIGINS_MAX_ENTRIES
            or candidate_bytes > _ALLOWED_EMBED_ORIGINS_MAX_BYTES
        ):
            continue
        origins.append(origin)
        seen.add(origin.value)
        encoded_bytes = candidate_bytes
    return SecurityPolicy(tuple(origins))


def _security_policy(
    raw_origins: tuple[str, ...],
    *,
    encoded: str,
) -> SecurityPolicy:
    count = len(raw_origins)
    if count > _ALLOWED_EMBED_ORIGINS_MAX_ENTRIES:
        raise ConfigurationError(
            f"{ALLOWED_EMBED_ORIGINS_ENV} contains {count} origin entries. "
            f"Maximum is {_ALLOWED_EMBED_ORIGINS_MAX_ENTRIES}."
        )
    try:
        encoded_bytes = len(encoded.encode("utf-8"))
    except UnicodeError as error:
        raise ConfigurationError(
            f"{ALLOWED_EMBED_ORIGINS_ENV} contains invalid Unicode"
        ) from error
    if encoded_bytes > _ALLOWED_EMBED_ORIGINS_MAX_BYTES:
        raise ConfigurationError(
            f"{ALLOWED_EMBED_ORIGINS_ENV} contains {encoded_bytes} UTF-8 bytes. "
            f"Maximum is {_ALLOWED_EMBED_ORIGINS_MAX_BYTES}."
        )
    if not raw_origins:
        return DEFAULT_SECURITY_POLICY

    origins: list[Origin] = []
    seen: set[str] = set()
    for raw_origin in raw_origins:
        try:
            origin = _canonical_origin(raw_origin)
        except (UnicodeError, ValueError) as error:
            raise ConfigurationError(
                f"{ALLOWED_EMBED_ORIGINS_ENV} contains invalid origin {raw_origin!r}"
            ) from error
        if origin.value not in seen:
            seen.add(origin.value)
            origins.append(origin)
    return SecurityPolicy(tuple(origins))


def _canonical_origin(raw_origin: str) -> Origin:
    if any(unicodedata.category(character) == "Cc" for character in raw_origin):
        raise ValueError("control character")
    value = raw_origin.strip(" ")
    if not value or "?" in value or "#" in value or "*" in value:
        raise ValueError("invalid origin component")

    parsed = urlsplit(value)
    scheme = parsed.scheme.casefold()
    hostname = parsed.hostname
    port = parsed.port
    if (
        scheme not in {"http", "https"}
        or not parsed.netloc
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("origin shape")

    authority = parsed.netloc.rsplit("@", maxsplit=1)[-1]
    _validate_authority(authority, hostname, port)
    canonical_host = _canonical_host(hostname)
    default_port = 80 if scheme == "http" else 443
    port_suffix = "" if port is None or port == default_port else f":{port}"
    return Origin(f"{scheme}://{canonical_host}{port_suffix}")


def _validate_authority(authority: str, hostname: str, port: int | None) -> None:
    has_port_marker = False
    if authority.startswith("["):
        closing_bracket = authority.find("]")
        if closing_bracket < 0:
            raise ValueError("hostname")
        host_value = authority[1:closing_bracket]
        port_value = authority[closing_bracket + 1 :]
        if port_value.startswith(":"):
            has_port_marker = True
            port_value = port_value[1:]
        elif port_value:
            raise ValueError("authority")
    else:
        host_value, separator, port_value = authority.rpartition(":")
        has_port_marker = bool(separator)
        if not separator:
            host_value = authority
            port_value = ""
    if host_value.casefold() != hostname.casefold():
        raise ValueError("hostname")
    if port is None:
        if has_port_marker:
            raise ValueError("port")
        return
    if (
        not port_value.isascii()
        or not port_value.isdecimal()
        or int(port_value) != port
    ):
        raise ValueError("port")


def _canonical_host(hostname: str) -> str:
    if not hostname.isascii() or "%" in hostname:
        raise ValueError("hostname")
    try:
        address = ip_address(hostname)
    except ValueError:
        normalized = hostname.casefold()
        labels = (
            normalized[:-1].split(".")
            if normalized.endswith(".")
            else normalized.split(".")
        )
        if (
            not labels
            or any(_HOST_LABEL.fullmatch(label) is None for label in labels)
            or len(normalized.rstrip(".")) > 253
            or _looks_like_legacy_ipv4(labels)
        ):
            raise ValueError("hostname") from None
        return normalized
    if isinstance(address, IPv6Address):
        return f"[{address.compressed}]"
    return address.compressed


def _looks_like_legacy_ipv4(labels: list[str]) -> bool:
    if len(labels) > 4:
        return False
    return all(
        label.isdecimal()
        or (
            label.casefold().startswith("0x")
            and len(label) > 2
            and all(
                character in "0123456789abcdef" for character in label[2:].casefold()
            )
        )
        for label in labels
    )
