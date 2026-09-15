"""Start the pinned Marimo editor runtime for configured Studio notebooks."""

from __future__ import annotations

import json
import re
from html import escape
from importlib.resources import files
from typing import cast
from urllib.parse import urlsplit, urlunsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from marimo_studio._delivery.urls import (
    PRIVATE_QUERY_KEYS,
    QUERY_OPERATION_QUERY_PARAM,
)
from marimo_studio.errors import ProtocolError

_MOUNT_VALUE = "value: Object.freeze("
_CELL_EDITOR_ASSET = re.compile(r"^/assets/cell-editor-[A-Za-z0-9_-]+\.js$")
_CONFIG_ASSET = re.compile(r"^/assets/config-[A-Za-z0-9_-]+\.js$")
_CELLS_ASSET = re.compile(r"^/assets/cells-[A-Za-z0-9_-]+\.js$")
_INDEX_ASSET = re.compile(r"^/assets/index-[A-Za-z0-9_-]+\.js$")
_PANELS_ASSET = re.compile(r"^/assets/panels-[A-Za-z0-9_-]+\.js$")
_COPILOT_EXTENSION = b"ad.of(Bt())"
_GATED_COPILOT_EXTENSION = b"e.copilot===`github`?ad.of(Bt()):[]"
_COPILOT_LSP_URL = b"this.formatWsURL(`/lsp/${e}`)"
_STUDIO_COPILOT_LSP_URL = (
    b"new URL(this.formatWsURL(`/lsp/${e}`).toString().replace("
    b'"/_marimo-studio/editor/lsp/","/lsp/"))'
)
_IMMEDIATE_LSP_RECONNECT = b"queueMicrotask(()=>this.reconnect())"
_BOUNDED_LSP_RECONNECT = (
    b"this.options.onConnectionFailure?this.options.onConnectionFailure(t):"
    b"setTimeout(()=>{this.isClosed||this.reconnect()},this.options.retryDelayMs)"
)
# Keep Marimo's save barrier and transaction queue around Studio admission.
_DOCUMENT_CHANGE_QUEUE = b"var $H=[],eU=[]"
_NATIVE_DOCUMENT_TRANSACTION = b"await rd().sendDocumentTransaction({changes:t})"
_ORDERED_DOCUMENT_TRANSACTION = (
    b"await marimoStudioSendDocumentTransaction({changes:t})"
)
_DOCUMENT_RUNTIME = (
    files("marimo_studio._compat.server").joinpath("editor_document.js").read_bytes()
)
_ORDERED_DOCUMENT_CHANGE_QUEUE = b"""
var marimoStudioPendingTransactions=[];
var marimoStudioDocumentTransactions=createStudioDocumentTransactions({
  takeChanges:()=>marimoStudioPendingTransactions.shift()??[],
  sendTransaction:request=>rd().sendDocumentTransaction(request),
});
function marimoStudioSendDocumentTransaction(request){
  marimoStudioPendingTransactions.push(request.changes);
  return marimoStudioDocumentTransactions.flush();
}
marimoStudioAwaitDocumentMutation=marimoStudioDocumentTransactions.awaitMutation;
marimoStudioDocumentMutationGeneration=marimoStudioDocumentTransactions.generation;
marimoStudioReportDocumentSave=marimoStudioDocumentTransactions.reportSave;
marimoStudioFlushDocumentChanges=lU;
marimoStudioFlushBeforeDocumentSave=marimoStudioDocumentTransactions.flush;
var $H=[],eU=[]
"""
_CELLS_EXPORT = b",RB as zt};"
_ORDERED_CELLS_EXPORT = (
    b",RB as zt,createStudioDocumentRequests as studioCreateDocumentRequests,"
    b"marimoStudioAwaitDocumentMutation as studioAwaitDocumentMutation,"
    b"marimoStudioDocumentMutationGeneration as studioDocumentMutationGeneration,"
    b"marimoStudioFlushDocumentChanges as studioFlushDocumentChanges,"
    b"marimoStudioFlushBeforeDocumentSave as studioFlushBeforeDocumentSave,"
    b"marimoStudioReportDocumentSave as studioReportDocumentSave};"
)
_INDEX_CELLS_IMPORT = b'zo as $e}from"./cells-'
_ORDERED_INDEX_CELLS_IMPORT = (
    b"zo as $e,studioCreateDocumentRequests,studioAwaitDocumentMutation,"
    b"studioFlushDocumentChanges,studioFlushBeforeDocumentSave,"
    b'studioDocumentMutationGeneration,studioReportDocumentSave}from"./cells-'
)
_NETWORK_SEND_SAVE = (
    b"sendSave:t=>e().POST(`/api/kernel/save`,{body:t,parseAs:`text`,params:n()})"
    b".then(lp)"
)
_NETWORK_SEND_DOCUMENT_TRANSACTION = (
    b"sendDocumentTransaction:async t=>(await sn(),e().POST("
    b"`/api/document/transaction`,"
    b"{body:t,params:n()}).then(lp))"
)
_NETWORK_REQUEST_FACTORY = b"n=()=>({header:t()});return{sendComponentValues:"
_DOCUMENT_NETWORK_BOOTSTRAP = b"""
const marimoStudioDocumentRequests=studioCreateDocumentRequests({
  flush:()=>studioFlushDocumentChanges(),
  flushBeforeSave:()=>studioFlushBeforeDocumentSave(),
  awaitMutation:()=>studioAwaitDocumentMutation(),
  generation:()=>studioDocumentMutationGeneration(),
  reportSave:(generation,succeeded)=>studioReportDocumentSave(generation,succeeded),
}, {
  post:(...args)=>e().POST(...args),
  waitForConnection:()=>sn(),
  params:()=>n(),
  handleResponse:result=>lp(result),
});
"""
_ORDERED_NETWORK_SEND_DOCUMENT_TRANSACTION = (
    b"sendDocumentTransaction:request=>"
    b"marimoStudioDocumentRequests.sendDocumentTransaction(request)"
)
_ORDERED_NETWORK_SEND_SAVE = (
    b"sendSave:request=>marimoStudioDocumentRequests.sendSave(request)"
)
_NETWORK_SEND_RUN = (
    b"sendRun:async t=>(await sn(),e().POST(`/api/kernel/run`,{body:t,params:n()})"
    b".then(lp))"
)
_ORDERED_NETWORK_SEND_RUN = (
    b"sendRun:request=>marimoStudioDocumentRequests.sendRun(request)"
)
_QUERY_PARAM_HANDLERS = (
    b"var jn={append:e=>{let t=new URL(window.location.href);t.searchParams."
    b"append(e.key,e.value),window.history.pushState({},``,`${t.pathname}${t"
    b".search}`)},set:e=>{let t=new URL(window.location.href);Array.isArray("
    b"e.value)?(t.searchParams.delete(e.key),e.value.forEach(n=>t.searchPara"
    b"ms.append(e.key,n))):t.searchParams.set(e.key,e.value),window.history."
    b"pushState({},``,`${t.pathname}${t.search}`)},delete:e=>{let t=new URL("
    b"window.location.href);e.value==null?t.searchParams.delete(e.key):t.sea"
    b"rchParams.delete(e.key,e.value),window.history.pushState({},``,`${t.pa"
    b"thname}${t.search}`)},clear:()=>{let e=new URL(window.location.href);e"
    b".search=``,window.history.pushState({},``,`${e.pathname}${e.search}`)}"
    b"};"
)
_RETAINED_QUERY_KEYS_JSON = json.dumps(
    sorted(PRIVATE_QUERY_KEYS),
    ensure_ascii=True,
    separators=(",", ":"),
).encode()
_IMMUTABLE_QUERY_KEYS_JSON = json.dumps(
    sorted(PRIVATE_QUERY_KEYS - {QUERY_OPERATION_QUERY_PARAM}),
    ensure_ascii=True,
    separators=(",", ":"),
).encode()
_PROTECTED_QUERY_PARAM_HANDLERS = (
    b"const marimoStudioImmutableQueryKeys=new Set("
    + _IMMUTABLE_QUERY_KEYS_JSON
    + b"),marimoStudioRetainedQueryKeys=new Set("
    + _RETAINED_QUERY_KEYS_JSON
    + b'),marimoStudioPushQuery=t=>window.history.pushState({},"",'
    b"`${t.pathname}${t.search}${t.hash}`),jn={append:t=>{if("
    b"marimoStudioImmutableQueryKeys.has(t.key))return;let A=new URL("
    b"window.location.href);"
    b"A.searchParams.append(t.key,t.value),marimoStudioPushQuery(A)},set:t=>{if("
    b"marimoStudioImmutableQueryKeys.has(t.key))return;let A=new URL("
    b"window.location.href);"
    b"Array.isArray(t.value)?(A.searchParams.delete(t.key),t.value.forEach(e=>"
    b"A.searchParams.append(t.key,e))):A.searchParams.set(t.key,t.value),"
    b"marimoStudioPushQuery(A)},delete:t=>{if(marimoStudioImmutableQueryKeys.has("
    b"t.key))return;let A=new URL(window.location.href);t.value==null?"
    b"A.searchParams.delete(t.key):A.searchParams.delete(t.key,t.value),"
    b"marimoStudioPushQuery(A)},clear:()=>{let t=new URL(window.location.href);"
    b"for(let A of new Set(t.searchParams.keys()))marimoStudioRetainedQueryKeys.has(A)"
    b"||t.searchParams.delete(A);marimoStudioPushQuery(t)}};"
)
_WELCOME_TEXTURE_PRELOADS = tuple(
    re.compile(
        rf'^[ \t]*<link rel="preload" href="\./assets/{texture}-'
        r'[A-Za-z0-9_-]+\.png" as="image" />\r?\n',
        re.MULTILINE,
    )
    for texture in ("gradient", "noise")
)


class PrivateEditorRuntimeBootstrap:
    """Adapt native editor resources to Studio's live-session contract."""

    async def serve(
        self,
        app: ASGIApp,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        resource_path: str,
        runtime_url: str,
        eager_runtime: bool,
        entrypoint_url: str | None = None,
        bound_editor: bool = True,
    ) -> bool:
        if scope["type"] != "http" or scope.get("method") != "GET":
            return False
        document = resource_path.rstrip("/") == ""
        cell_editor = _CELL_EDITOR_ASSET.fullmatch(resource_path) is not None
        config_asset = _CONFIG_ASSET.fullmatch(resource_path) is not None
        cells_asset = _CELLS_ASSET.fullmatch(resource_path) is not None
        index_asset = _INDEX_ASSET.fullmatch(resource_path) is not None
        panels_asset = _PANELS_ASSET.fullmatch(resource_path) is not None
        if not any(
            (
                document,
                cell_editor,
                config_asset,
                cells_asset,
                index_asset,
                panels_asset,
            )
        ):
            return False
        start: Message | None = None
        body = bytearray()

        async def capture(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                if start is not None:
                    raise ProtocolError("Marimo started the editor response twice")
                start = message
                return
            if message["type"] == "http.response.pathsend":
                raise ProtocolError("Marimo bypassed the editor asset response body")
            if message["type"] != "http.response.body":
                await send(message)
                return
            body.extend(message.get("body", b""))
            if message.get("more_body", False):
                return
            if start is None:
                raise ProtocolError("Marimo omitted the editor response status")
            original = bytes(body)
            rewritten = original
            if document and _is_html(start):
                rewritten = self.rewrite(
                    original,
                    runtime_url=runtime_url,
                    eager_runtime=eager_runtime,
                    entrypoint_url=entrypoint_url,
                )
            elif cell_editor:
                if not _is_javascript(start):
                    raise ProtocolError(
                        "Marimo did not return a complete cell editor asset"
                    )
                rewritten = _gate_copilot_extension(original)
            elif config_asset and b"getLSPURL" in original:
                if not _is_javascript(start):
                    raise ProtocolError(
                        "Marimo did not return a complete runtime configuration asset"
                    )
                rewritten = _route_copilot_lsp(original)
            elif cells_asset:
                if not _is_javascript(start):
                    raise ProtocolError(
                        "Marimo did not return the notebook cell state asset"
                    )
                rewritten = _backoff_lsp_reconnects(
                    _serialize_document_transactions(original)
                    if bound_editor
                    else original
                )
            elif index_asset and bound_editor:
                if not _is_javascript(start):
                    raise ProtocolError(
                        "Marimo did not return the editor network asset"
                    )
                rewritten = _await_document_transactions_before_network_run(original)
            elif panels_asset and bound_editor:
                if not _is_javascript(start):
                    raise ProtocolError(
                        "Marimo did not return the editor query handler asset"
                    )
                rewritten = _protect_editor_query_parameters(original)
            await send(
                _response_headers(
                    start,
                    len(rewritten),
                    no_store=(
                        rewritten is not original
                        or cells_asset
                        or index_asset
                        or panels_asset
                    ),
                )
            )
            await send({"type": "http.response.body", "body": rewritten})

        await app(_fresh_scope(scope), receive, capture)
        return True

    def rewrite(
        self,
        document: bytes,
        *,
        runtime_url: str,
        eager_runtime: bool = True,
        entrypoint_url: str | None = None,
    ) -> bytes:
        """Adapt the pinned editor document for Studio's notebook-first boot."""
        try:
            source = document.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProtocolError(
                "Marimo returned a non-UTF-8 editor document"
            ) from error
        source = _strip_welcome_texture_preloads(source)
        if entrypoint_url is not None:
            source = source.replace(
                "</body>",
                (
                    f'<script type="module" src="{escape(entrypoint_url, quote=True)}">'
                    "</script></body>"
                ),
            )
        if not eager_runtime:
            return source.encode()
        marker = source.find(_MOUNT_VALUE)
        if marker < 0 or source.find(_MOUNT_VALUE, marker + 1) >= 0:
            raise ProtocolError("Marimo's editor mount configuration changed")
        runtime_start, runtime_end, configured = _mount_value(
            source,
            marker,
            "runtimeConfig",
        )
        if configured is None or configured == []:
            runtime = [{"url": _runtime_url(runtime_url), "lazy": False}]
        elif (
            isinstance(configured, list)
            and configured
            and isinstance(configured[0], dict)
        ):
            runtime = [{**configured[0], "lazy": False}, *configured[1:]]
        else:
            raise ProtocolError("Marimo's editor runtime configuration changed")

        overrides_start, overrides_end, configured_overrides = _mount_value(
            source,
            marker,
            "configOverrides",
        )
        if not isinstance(configured_overrides, dict):
            raise ProtocolError("Marimo's editor configuration overrides changed")
        runtime_overrides = configured_overrides.get("runtime", {})
        if not isinstance(runtime_overrides, dict):
            raise ProtocolError("Marimo's editor runtime overrides changed")
        overrides = {
            **configured_overrides,
            "runtime": {**runtime_overrides, "auto_instantiate": True},
        }

        updates = (
            (runtime_start, runtime_end, runtime),
            (overrides_start, overrides_end, overrides),
        )
        for start, end, value in sorted(updates, reverse=True):
            replacement = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            source = f"{source[:start]}{replacement}{source[end:]}"
        return source.encode()


def _strip_welcome_texture_preloads(source: str) -> str:
    for pattern in _WELCOME_TEXTURE_PRELOADS:
        source, count = pattern.subn("", source)
        if count != 1:
            raise ProtocolError("Marimo's editor welcome texture preloads changed")
    return source


def _runtime_url(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((*parts[:3], "", ""))


def _mount_value(
    source: str,
    mount_start: int,
    key: str,
) -> tuple[int, int, object]:
    marker = f'"{key}":'
    value_marker = source.find(marker, mount_start + len(_MOUNT_VALUE))
    if value_marker < 0 or source.find(marker, value_marker + 1) >= 0:
        raise ProtocolError(f"Marimo's editor {key} field changed")
    start = value_marker + len(marker)
    while start < len(source) and source[start].isspace():
        start += 1
    try:
        value, end = json.JSONDecoder().raw_decode(source, start)
    except json.JSONDecodeError as error:
        raise ProtocolError(f"Marimo's editor {key} field is invalid") from error
    return start, end, value


def _gate_copilot_extension(document: bytes) -> bytes:
    if document.count(_COPILOT_EXTENSION) != 1:
        raise ProtocolError("Marimo's cell editor completion bundle changed")
    return document.replace(
        _COPILOT_EXTENSION,
        _GATED_COPILOT_EXTENSION,
        1,
    )


def _route_copilot_lsp(document: bytes) -> bytes:
    if document.count(_COPILOT_LSP_URL) != 2:
        raise ProtocolError("Marimo's editor runtime URL bundle changed")
    return document.replace(
        _COPILOT_LSP_URL,
        _STUDIO_COPILOT_LSP_URL,
        1,
    )


def _backoff_lsp_reconnects(document: bytes) -> bytes:
    return _replace_pinned_asset(
        document,
        _IMMEDIATE_LSP_RECONNECT,
        _BOUNDED_LSP_RECONNECT,
        "editor LSP reconnect scheduler",
    )


def _serialize_document_transactions(document: bytes) -> bytes:
    rewritten = _replace_pinned_asset(
        (
            b"var marimoStudioAwaitDocumentMutation,"
            b"marimoStudioDocumentMutationGeneration,"
            b"marimoStudioFlushDocumentChanges,marimoStudioFlushBeforeDocumentSave,"
            b"marimoStudioReportDocumentSave;" + _DOCUMENT_RUNTIME + document
        ),
        _DOCUMENT_CHANGE_QUEUE,
        _ORDERED_DOCUMENT_CHANGE_QUEUE,
        "document transaction queue",
    )
    rewritten = _replace_pinned_asset(
        rewritten,
        _NATIVE_DOCUMENT_TRANSACTION,
        _ORDERED_DOCUMENT_TRANSACTION,
        "native document transaction dispatch",
    )
    return _replace_pinned_asset(
        rewritten,
        _CELLS_EXPORT,
        _ORDERED_CELLS_EXPORT,
        "notebook cell exports",
    )


def _await_document_transactions_before_network_run(document: bytes) -> bytes:
    rewritten = _replace_pinned_asset(
        document,
        _INDEX_CELLS_IMPORT,
        _ORDERED_INDEX_CELLS_IMPORT,
        "editor network cell imports",
    )
    rewritten = _replace_pinned_asset(
        rewritten,
        _NETWORK_REQUEST_FACTORY,
        b"n=()=>({header:t()});"
        + _DOCUMENT_NETWORK_BOOTSTRAP
        + b"return{sendComponentValues:",
        "editor network request factory",
    )
    rewritten = _replace_pinned_asset(
        rewritten,
        _NETWORK_SEND_DOCUMENT_TRANSACTION,
        _ORDERED_NETWORK_SEND_DOCUMENT_TRANSACTION,
        "editor network document transaction",
    )
    rewritten = _replace_pinned_asset(
        rewritten,
        _NETWORK_SEND_SAVE,
        _ORDERED_NETWORK_SEND_SAVE,
        "editor network notebook save",
    )
    return _replace_pinned_asset(
        rewritten,
        _NETWORK_SEND_RUN,
        _ORDERED_NETWORK_SEND_RUN,
        "editor network cell run",
    )


def _protect_editor_query_parameters(document: bytes) -> bytes:
    return _replace_pinned_asset(
        document,
        _QUERY_PARAM_HANDLERS,
        _PROTECTED_QUERY_PARAM_HANDLERS,
        "editor query parameter handlers",
    )


def _replace_pinned_asset(
    document: bytes,
    expected: bytes,
    replacement: bytes,
    label: str,
) -> bytes:
    if document.count(expected) != 1:
        raise ProtocolError(f"Marimo's {label} changed")
    return document.replace(expected, replacement, 1)


def _fresh_scope(scope: Scope) -> Scope:
    updated = dict(scope)
    updated["headers"] = [
        (name, value)
        for name, value in cast(list[tuple[bytes, bytes]], scope.get("headers", []))
        if name.lower()
        not in {
            b"accept-encoding",
            b"if-modified-since",
            b"if-none-match",
            b"if-range",
            b"range",
        }
    ]
    updated["headers"].append((b"accept-encoding", b"identity"))
    extensions = dict(cast(dict[str, object], scope.get("extensions", {})))
    extensions.pop("http.response.pathsend", None)
    updated["extensions"] = extensions
    return updated


def _response_headers(
    start: Message,
    length: int,
    *,
    no_store: bool = False,
) -> Message:
    replaced = {b"content-length"}
    if no_store:
        replaced.update(
            {
                b"accept-ranges",
                b"cache-control",
                b"content-range",
                b"etag",
                b"last-modified",
            }
        )
    headers = [
        (name, value)
        for name, value in cast(list[tuple[bytes, bytes]], start.get("headers", []))
        if name.lower() not in replaced
    ]
    headers.append((b"content-length", str(length).encode()))
    if no_store:
        headers.append((b"cache-control", b"no-store"))
    return {**start, "headers": headers}


def _is_html(start: Message) -> bool:
    if start.get("status") != 200:
        return False
    return any(
        name.lower() == b"content-type" and value.lower().startswith(b"text/html")
        for name, value in cast(list[tuple[bytes, bytes]], start.get("headers", []))
    )


def _is_javascript(start: Message) -> bool:
    if start.get("status") != 200:
        return False
    return any(
        name.lower() == b"content-type"
        and value.lower().startswith((b"text/javascript", b"application/javascript"))
        for name, value in cast(list[tuple[bytes, bytes]], start.get("headers", []))
    )
