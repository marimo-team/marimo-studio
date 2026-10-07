"""Build Marimo server applications and inspect their test state."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from html.parser import HTMLParser
from types import SimpleNamespace
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit


class Response(Protocol):
    """The response surface that Studio's URL helpers read."""

    @property
    def url(self) -> object: ...

    @property
    def text(self) -> str: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def json(self) -> Any: ...


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


def _resolved(response: Response, reference: str) -> str:
    """Resolve a Studio reference against the URL that carried it."""
    return urljoin(str(response.url), reference)


def _redirect_target(response: Response) -> str:
    return _resolved(response, response.headers["location"])


def _resolved_urls(response: Response, record: dict[str, Any]) -> dict[str, Any]:
    urls = {name: _resolved(response, url) for name, url in record["urls"].items()}
    return {**record, "urls": urls}


def _studio_bootstrap(response: Response) -> dict[str, Any]:
    parser = _BootstrapParser()
    parser.feed(response.text)
    return _resolved_urls(response, json.loads("".join(parser.parts)))


def _studio_host(response: Response) -> dict[str, Any]:
    parser = _BootstrapParser("marimo-studio-host")
    parser.feed(response.text)
    return _resolved_urls(response, json.loads("".join(parser.parts)))


def _runtime_config(response: Response) -> dict[str, Any]:
    """Return a runtime configuration with URLs resolved as the browser does."""
    config = response.json()
    return {
        **config,
        "runtime": _resolved_urls(response, config["runtime"]),
        **{
            key: _resolved(response, config[key])
            for key in ("rootUrl", "publicRootUrl", "documentRootUrl", "supportUrl")
        },
    }


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


def _artifact_base(response: Response) -> str:
    match = re.search(r'<base href="([^"]+)">', response.text)
    assert match is not None
    return _resolved(response, match.group(1))


def _mount_support_url(response: Response) -> str:
    """Resolve the mount support URL against the document base."""
    return urljoin(
        _artifact_base(response),
        _editor_mount_value(response.text, "supportUrl"),
    )


def _presentation_frame_url(response: Response) -> str:
    parser = _PresentationFrameParser()
    parser.feed(response.text)
    assert parser.src is not None
    return _resolved(response, parser.src)


def _presentation_frame_sandbox(document: str) -> frozenset[str]:
    parser = _PresentationFrameParser()
    parser.feed(document)
    assert parser.sandbox is not None
    return parser.sandbox


def _presentation_wrapper_config(document: str) -> dict[str, Any]:
    parser = _BootstrapParser("marimo-studio-wrapper-config")
    parser.feed(document)
    config = json.loads("".join(parser.parts))
    assert isinstance(config, dict)
    return config


def _presentation_fallback_url(response: Response) -> str:
    fallback = _presentation_wrapper_config(response.text)["fallbackUrl"]
    assert isinstance(fallback, str)
    return _resolved(response, fallback)


def _assert_server_runtime(runtime: dict[str, Any], url: str) -> None:
    capability = runtime["data"]["capabilityToken"]
    assert isinstance(capability, str)
    transport = runtime["urls"]["transport"]
    assert f"/_marimo-studio/presentation/{capability}/" in transport
    assert transport.startswith(url)
    assert re.fullmatch(r"[0-9a-f]{64}", runtime["data"]["serverInstance"])


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
        last_executed_code={row.id: row.code for row in rows},
        cell_notifications={},
    )
    session.app_file_manager = SimpleNamespace(
        app=_LiveTestApp(document),
        path=path,
    )
    if initialization_id is not None:
        session.initialization_id = initialization_id
    return session
