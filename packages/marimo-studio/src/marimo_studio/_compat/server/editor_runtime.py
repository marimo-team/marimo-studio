"""Start the pinned Marimo editor runtime for configured Studio notebooks."""

from __future__ import annotations

import json
import re
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
_COPILOT_EXTENSION = b"Ru.of(Rm())"
_GATED_COPILOT_EXTENSION = b't.copilot==="github"?Ru.of(Rm()):[]'
_COPILOT_LSP_URL = b"this.formatWsURL(`/lsp/${t}`)"
_STUDIO_COPILOT_LSP_URL = (
    b"new URL(this.formatWsURL(`/lsp/${t}`).toString().replace("
    b'"/_marimo-studio/editor/lsp/","/lsp/"))'
)
_IMMEDIATE_LSP_RECONNECT = b"queueMicrotask(()=>this.reconnect())"
_BOUNDED_LSP_RECONNECT = (
    b"this.options.onConnectionFailure?this.options.onConnectionFailure(t):"
    b"setTimeout(()=>{this.isClosed||this.reconnect()},this.options.retryDelayMs)"
)
_DOCUMENT_CHANGE_QUEUE = (
    b"var _m=[],$P=Sg(()=>{let e=FP(_m);_m=[],e.length!==0&&"
    b"Sr().sendDocumentTransaction({changes:e})},400);"
)
_ORDERED_DOCUMENT_CHANGE_QUEUE = (
    b"var _m=[],marimoStudioDocumentGeneration=0,"
    b"marimoStudioAdmittedDocumentGeneration=0,"
    b"marimoStudioDocumentOperationSequence=0,"
    b"marimoStudioPendingDocumentGeneration=0,marimoStudioPendingDocumentOperation,"
    b"marimoStudioRetryDocumentChanges,marimoStudioDocumentBarrier,"
    b"marimoStudioHasDocumentBridge=()=>{try{return globalThis.frameElement!==null"
    b'&&globalThis.frameElement.hasAttribute("data-marimo-studio-document-'
    b'mutation-bridge")}catch{return!1}},marimoStudioCurrentDocumentGeneration='
    b"()=>marimoStudioDocumentGeneration,marimoStudioReportSave=(e,t)=>{"
    b"if(e!==0&&marimoStudioHasDocumentBridge())try{globalThis.parent.postMessage("
    b'{schema:1,type:t?"marimo-studio:editor-'
    b'document-saved":"marimo-studio:editor-document-save-failed",generation:'
    b"e},globalThis.location.origin)}catch{}},"
    b"marimoStudioReportDocumentTransactionFailure=e=>{if("
    b"marimoStudioHasDocumentBridge())try{globalThis.parent.postMessage({schema:1,"
    b'type:"marimo-studio:editor-document-transaction-failed",generation:e},'
    b"globalThis.location.origin)}catch{}},"
    b"marimoStudioReportDocumentTransactionApplied=(e,t)=>{if("
    b"marimoStudioHasDocumentBridge())try{globalThis.parent.postMessage({schema:1,"
    b'type:"marimo-studio:editor-document-transaction-applied",generation:e,'
    b"changed:t},"
    b"globalThis.location.origin)}catch{}},"
    b"marimoStudioAnnounceDocumentMutation="
    b"e=>!marimoStudioHasDocumentBridge()?"
    b"Promise.resolve():new Promise((t,n)=>{let o=new MessageChannel,i=!1,"
    b"a=(r,l)=>{i||(i=!0,clearTimeout(c),globalThis.removeEventListener("
    b'"pagehide",s),o.port1.onmessage=null,o.port1.onmessageerror=null,'
    b'o.port1.close(),r(l))},s=()=>a(n,new DOMException("The Studio document '
    b'barrier closed.","AbortError")),c=setTimeout(()=>a(n,new DOMException('
    b'"Studio did not acknowledge the document change.","TimeoutError")),'
    b"5e3);o.port1.onmessage=r=>{let l=r.data;l&&l.schema===1&&"
    b'(l.type==="marimo-studio:editor-document-mutation-ready"&&l.generation===e?'
    b"a(t):l.type==="
    b'"marimo-studio:editor-document-mutation-failed"&&a(n,new DOMException('
    b'"Studio could not pause the presentation.","AbortError")))},'
    b'o.port1.onmessageerror=()=>a(n,new DOMException("Studio rejected the '
    b'document change acknowledgement.","DataError")),o.port1.start(),'
    b'globalThis.addEventListener("pagehide",s,{once:!0});try{globalThis.parent.'
    b'postMessage({schema:1,type:"marimo-studio:editor-document-mutation",'
    b"generation:e},globalThis.location.origin,[o.port2])}catch(r){a(n,r)}}),"
    b"marimoStudioAwaitMutation=()=>{let e=marimoStudioDocumentGeneration;"
    b"if(e===marimoStudioAdmittedDocumentGeneration)return Promise.resolve();"
    b"if(marimoStudioDocumentBarrier)return marimoStudioDocumentBarrier;let t="
    b"marimoStudioAnnounceDocumentMutation(e).then(()=>{e==="
    b"marimoStudioDocumentGeneration&&(marimoStudioAdmittedDocumentGeneration=e)});"
    b"marimoStudioDocumentBarrier=t;let n=()=>{marimoStudioDocumentBarrier===t&&"
    b"(marimoStudioDocumentBarrier=void 0)};return t.then(n,n),t.catch(()=>{}),t},"
    b"marimoStudioDocumentDrain,"
    b"marimoStudioDrainDocumentChanges=async()=>{for(;;){let e="
    b"marimoStudioRetryDocumentChanges??FP(_m);marimoStudioRetryDocumentChanges?"
    b"marimoStudioRetryDocumentChanges=void 0:_m=[];if(e.length===0)return null;"
    b"try{marimoStudioPendingDocumentGeneration===0"
    b"&&(marimoStudioDocumentGeneration+=1,marimoStudioPendingDocumentGeneration="
    b"marimoStudioDocumentGeneration),marimoStudioPendingDocumentOperation??=Array."
    b"from(crypto.getRandomValues(new Uint32Array(4)),e=>e.toString(36).padStart(7,"
    b'"0")).join("")+'
    b'"-"+(++marimoStudioDocumentOperationSequence).toString(36).padStart(7,"0");'
    b"await marimoStudioAwaitMutation();let n=await Sr()."
    b"sendDocumentTransaction({changes:e,studioOperationId:"
    b"marimoStudioPendingDocumentOperation});if(typeof n!=="
    b'"boolean")throw new Error("Studio document transaction evidence is '
    b'unavailable");'
    b"marimoStudioReportDocumentTransactionApplied("
    b"marimoStudioPendingDocumentGeneration,n)}catch(t){throw "
    b"marimoStudioReportDocumentTransactionFailure("
    b"marimoStudioPendingDocumentGeneration),"
    b"marimoStudioAdmittedDocumentGeneration=Math.max(0,"
    b"marimoStudioPendingDocumentGeneration-1),marimoStudioDocumentBarrier=void 0,"
    b"marimoStudioRetryDocumentChanges=e,t}marimoStudioPendingDocumentGeneration=0,"
    b"marimoStudioPendingDocumentOperation=void 0}};"
    b"marimoStudioAwaitDocumentMutation=marimoStudioAwaitMutation;"
    b"marimoStudioDocumentMutationGeneration=marimoStudioCurrentDocumentGeneration;"
    b"marimoStudioReportDocumentSave=marimoStudioReportSave;"
    b"marimoStudioFlushDocumentChanges=()=>{if($P.cancel(),"
    b"marimoStudioDocumentDrain)return marimoStudioDocumentDrain;let e="
    b"marimoStudioDrainDocumentChanges();marimoStudioDocumentDrain=e;let t=()=>{"
    b"marimoStudioDocumentDrain===e&&(marimoStudioDocumentDrain=void 0)};return "
    b"e.then(t,t),e};var $P=Sg(()=>{marimoStudioFlushDocumentChanges().catch("
    b"()=>{})},400);"
)
_CELLS_EXPORT = b",CT as zt};"
_ORDERED_CELLS_EXPORT = (
    b",CT as zt,marimoStudioAwaitDocumentMutation as studioAwaitDocumentMutation,"
    b"marimoStudioDocumentMutationGeneration as studioDocumentMutationGeneration,"
    b"marimoStudioFlushDocumentChanges as studioFlushDocumentChanges,"
    b"marimoStudioReportDocumentSave as studioReportDocumentSave};"
)
_INDEX_CELLS_IMPORT = b'zr as zj,__tla as Mj}from"./cells-'
_ORDERED_INDEX_CELLS_IMPORT = (
    b"zr as zj,studioAwaitDocumentMutation,studioFlushDocumentChanges,"
    b"studioDocumentMutationGeneration,studioReportDocumentSave,"
    b'__tla as Mj}from"./cells-'
)
_NETWORK_SEND_SAVE = (
    b'sendSave:n=>t().POST("/api/kernel/save",{body:n,parseAs:"text",params:r()})'
    b".then(ve)"
)
_NETWORK_SEND_DOCUMENT_TRANSACTION = (
    b"sendDocumentTransaction:async n=>(await st(),t().POST("
    b'"/api/document/transaction",'
    b"{body:n,params:r()}).then(ve))"
)
_ORDERED_NETWORK_SEND_DOCUMENT_TRANSACTION = (
    b"sendDocumentTransaction:async n=>(await st(),t().POST("
    b'"/api/document/transaction",'
    b'{body:{changes:n.changes},headers:{"Marimo-Studio-Document-Operation":'
    b"n.studioOperationId},params:r()}).then(async e=>{await ve(e);let o=e.response."
    b'headers.get("marimo-studio-document-changed");if(o==="true")return!0;'
    b'if(o==="false")'
    b'return!1;throw new Error("Studio document transaction evidence is '
    b'unavailable")}))'
)
_ORDERED_NETWORK_SEND_SAVE = (
    b"sendSave:async n=>{await studioFlushDocumentChanges();let o="
    b"studioDocumentMutationGeneration();try{let i=await "
    b't().POST("/api/kernel/save",{body:n,parseAs:"text",params:r()}).then(ve);'
    b"return studioReportDocumentSave(o,!0),i}catch(i){throw "
    b"studioReportDocumentSave(o,!1),i}}"
)
_NETWORK_SEND_RUN = (
    b'sendRun:async n=>(await st(),t().POST("/api/kernel/run",{body:n,params:r()})'
    b".then(ve))"
)
_ORDERED_NETWORK_SEND_RUN = (
    b"sendRun:async n=>(await st(),await studioFlushDocumentChanges(),await "
    b"studioAwaitDocumentMutation(),t().POST("
    b'"/api/kernel/run",{body:n,params:r()}).then(ve))'
)
_QUERY_PARAM_HANDLERS = (
    b"const aA={append:t=>{let A=new URL(window.location.href);"
    b'A.searchParams.append(t.key,t.value),window.history.pushState({},"",'
    b"`${A.pathname}${A.search}`)},set:t=>{let A=new URL(window.location.href);"
    b"Array.isArray(t.value)?(A.searchParams.delete(t.key),t.value.forEach(e=>"
    b"A.searchParams.append(t.key,e))):A.searchParams.set(t.key,t.value),"
    b'window.history.pushState({},"",`${A.pathname}${A.search}`)},delete:t=>{'
    b"let A=new URL(window.location.href);t.value==null?A.searchParams.delete("
    b"t.key):A.searchParams.delete(t.key,t.value),window.history.pushState({},"
    b'"",`${A.pathname}${A.search}`)},clear:()=>{let t=new URL(window.location.href);'
    b't.search="",window.history.pushState({},"",`${t.pathname}${t.search}`)}};'
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
    b"`${t.pathname}${t.search}${t.hash}`),aA={append:t=>{if("
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
                )
            elif index_asset:
                if not _is_javascript(start):
                    raise ProtocolError(
                        "Marimo did not return the editor network asset"
                    )
                rewritten = _await_document_transactions_before_network_run(original)
            elif panels_asset:
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
    ) -> bytes:
        """Adapt the pinned editor document for Studio's notebook-first boot."""
        try:
            source = document.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProtocolError(
                "Marimo returned a non-UTF-8 editor document"
            ) from error
        source = _strip_welcome_texture_preloads(source)
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
            b"marimoStudioFlushDocumentChanges,marimoStudioReportDocumentSave;"
            + document
        ),
        _DOCUMENT_CHANGE_QUEUE,
        _ORDERED_DOCUMENT_CHANGE_QUEUE,
        "document transaction queue",
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
