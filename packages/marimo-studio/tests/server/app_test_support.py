"""Build Marimo server applications and inspect their test state."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from html.parser import HTMLParser
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class _BootstrapParser(HTMLParser):
    def __init__(self, script_id: str = "marimo-studio-bootstrap") -> None:
        super().__init__()
        self.script_id = script_id
        self._reading = False
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._reading = tag == "script" and dict(attrs).get("id") == self.script_id

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._reading = False

    def handle_data(self, data: str) -> None:
        if self._reading:
            self.parts.append(data)


class _PresentationFrameParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.src: str | None = None
        self.sandbox: frozenset[str] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = dict(attrs)
        if tag == "iframe" and values.get("id") == "marimo-studio-presentation":
            self.src = values.get("src")
            sandbox = values.get("sandbox")
            self.sandbox = frozenset(sandbox.split()) if sandbox is not None else None
        if (
            tag == "div"
            and values.get("id") == "marimo-studio-presentation"
            and "data-marimo-studio-frame-blueprint" in values
        ):
            sandbox = values.get("data-frame-sandbox")
            self.sandbox = frozenset(sandbox.split()) if sandbox is not None else None


class _RuntimeScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._reading = False
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = dict(attrs)
        self._reading = tag == "script" and "data-marimo-studio-runtime" in values

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._reading = False

    def handle_data(self, data: str) -> None:
        if self._reading:
            self.parts.append(data)


def _studio_bootstrap(document: str) -> dict[str, Any]:
    parser = _BootstrapParser()
    parser.feed(document)
    return json.loads("".join(parser.parts))


def _studio_host(document: str) -> dict[str, Any]:
    parser = _BootstrapParser("marimo-studio-host")
    parser.feed(document)
    return json.loads("".join(parser.parts))


def _editor_mount_value(document: str, key: str) -> Any:
    marker = f'"{key}":'
    start = document.index(marker) + len(marker)
    while document[start].isspace():
        start += 1
    value, _end = json.JSONDecoder().raw_decode(document, start)
    return value


def _runtime_mount_script(document: str) -> str:
    parser = _RuntimeScriptParser()
    parser.feed(document)
    scripts = [part for part in parser.parts if "__MARIMO_MOUNT_CONFIG__" in part]
    assert len(scripts) == 1
    return scripts[0]


def _artifact_base(document: str) -> str:
    match = re.search(r'<base href="([^"]+)">', document)
    assert match is not None
    return match.group(1)


def _presentation_frame_url(document: str) -> str:
    parser = _PresentationFrameParser()
    parser.feed(document)
    assert parser.src is not None
    return parser.src


def _presentation_frame_sandbox(document: str) -> frozenset[str]:
    parser = _PresentationFrameParser()
    parser.feed(document)
    assert parser.sandbox is not None
    return parser.sandbox


def _presentation_fallback_url(document: str) -> str:
    encoded = re.search(r"const config = Object\.freeze\((\{[^\n]+\})\);", document)
    assert encoded is not None
    fallback = json.loads(encoded.group(1))["fallbackUrl"]
    assert isinstance(fallback, str)
    return fallback


def _assert_server_runtime(data: dict[str, Any], url: str) -> None:
    capability = data["capabilityToken"]
    assert isinstance(capability, str)
    assert f"/_marimo-studio/presentation/{capability}/" in data["url"]
    assert data["url"].startswith(url)
    assert re.fullmatch(r"[0-9a-f]{64}", data["serverInstance"])


def _projection_request(
    config: dict[str, Any],
    kind: str,
    target: str,
    *,
    site_target: str | None = None,
    instance: str = "projection-1",
) -> dict[str, str]:
    expected = site_target or target
    site = next(
        item
        for item in config["mounts"]
        if item["kind"] == kind
        and (item["allowedTargets"] is None or expected in item["allowedTargets"])
    )
    return {
        "siteId": site["id"],
        "instanceId": instance,
        "target": target,
    }


def _projection_targets(config: dict[str, Any], kind: str) -> set[str]:
    return {
        target
        for site in config["mounts"]
        if site["kind"] == kind
        for target in site["allowedTargets"] or []
    }


def _view_support_url(config: dict[str, Any], route: str) -> str:
    value = config["supportUrl"]
    assert isinstance(value, str)
    support = urlsplit(value)
    return urlunsplit(support._replace(path=f"{support.path.rstrip('/')}/{route}"))


class _LiveTestApp:
    def __init__(self, document: SimpleNamespace) -> None:
        self._document = document

    @property
    def graph(self) -> Any:
        from marimo._ast.compiler import compile_cell
        from marimo._runtime.dataflow import DirectedGraph
        from marimo._types.ids import CellId_t

        graph = DirectedGraph()
        for row in self._document.cells:
            cell_id = CellId_t(str(row.id))
            graph.register_cell(
                cell_id,
                compile_cell(row.code, cell_id=cell_id),
            )
        return graph

    @property
    def cell_manager(self) -> SimpleNamespace:
        graph = self.graph
        return SimpleNamespace(valid_cells=lambda: tuple(graph.cells.items()))


class _LiveTestSession:
    document: SimpleNamespace
    session_view: SimpleNamespace
    app_file_manager: SimpleNamespace
    initialization_id: str


def _live_test_session(
    rows: Sequence[SimpleNamespace],
    *,
    path: str | None = None,
    initialization_id: str | None = None,
) -> _LiveTestSession:
    document = SimpleNamespace(cells=rows, version=0)
    session = _LiveTestSession()
    session.document = document
    session.session_view = SimpleNamespace(
        last_executed_code={row.id: row.code for row in rows}
    )
    session.app_file_manager = SimpleNamespace(
        app=_LiveTestApp(document),
        path=path,
    )
    if initialization_id is not None:
        session.initialization_id = initialization_id
    return session
