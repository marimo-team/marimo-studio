"""Contain provider-authored pages inside a trusted navigation shell.

The outer Studio document places the authored artifact in a sandboxed iframe
with an opaque browser origin. The parent owns allowed view navigation, public
query and fragment history, replay admission, readiness, errors, and agent
observation messages without giving the child access to Studio credentials or
same-origin server data.

Parent and child exchange a small set of validated messages. The shell keeps
browser back and reload behavior aligned with the selected view, preserves an
eligible live session across reloads, and recovers from browser page-cache
restoration while the authored page remains responsible for its own layout and
frontend code.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import cast

from htpy import (
    Node,
    body,
    div,
    head,
    html,
    iframe,
    meta,
    script,
    style,
    title,
)
from markupsafe import Markup

from marimo_studio._delivery.html import node_list, render

PRESENTATION_SANDBOX = (
    "allow-downloads allow-forms allow-modals allow-pointer-lock "
    "allow-popups allow-scripts"
)

_BRIDGE = r"""(() => {
  const config = Object.freeze(CONFIG);
  const allowedViews = new Set(config.views);
  const privateQueryKeys = new Set(config.privateQueryKeys);
  const frameBlueprint = document.querySelector(
    "#marimo-studio-presentation[data-marimo-studio-frame-blueprint]",
  );
  let frame = frameBlueprint
    ? undefined
    : document.querySelector("#marimo-studio-presentation");
  if (frame !== undefined && !(frame instanceof HTMLIFrameElement)) return;
  if (frameBlueprint !== null && !(frameBlueprint instanceof HTMLElement)) return;
  if (!frame && !frameBlueprint) return;
  let currentView = config.view;
  let currentSearch = location.search;
  let childIdentity;
  let documentClosed = false;
  let activeReplayUrl = config.fallbackUrl;
  const loadFrame = (url) => {
    if (documentClosed) return;
    activeReplayUrl = url;
    if (!frame) {
      const title = frameBlueprint?.dataset.frameTitle;
      const sandbox = frameBlueprint?.dataset.frameSandbox;
      const allow = frameBlueprint?.dataset.frameAllow;
      if (!frameBlueprint || !title || !sandbox || !allow) return;
      const created = document.createElement("iframe");
      created.id = "marimo-studio-presentation";
      created.title = title;
      created.setAttribute("sandbox", sandbox);
      created.setAttribute("allow", allow);
      created.src = url;
      frameBlueprint.replaceWith(created);
      frame = created;
      return;
    }
    frame.src = url;
  };
  const childMessages = new Set([
    "marimo-studio:navigate-view",
    "marimo-studio:query-change",
    "marimo-studio:replay-document",
    "marimo-studio:receiver-ready",
    "marimo-studio:receiver-unready",
    "marimo-studio:receiver-waiting",
    "marimo-studio:view-ready",
    "marimo-studio:view-sync-pending",
    "marimo-studio:view-diagnostics",
    "marimo-studio:view-error",
    "marimo-studio:view-observation",
  ]);
  const parentMessages = new Set([
    "marimo-studio:switch-view",
    "marimo-studio:presentation-change",
    "marimo-studio:receiver-admitted",
    "marimo-studio:observe-view",
  ]);
  const messageType = (value) =>
    value && typeof value === "object" && typeof value.type === "string"
      ? value.type
      : undefined;
  const boundedText = (value, maxBytes) =>
    typeof value === "string" && new TextEncoder().encode(value).length <= maxBytes;
  const navigationRequest = (value) =>
    value &&
    typeof value === "object" &&
    allowedViews.has(value.view) &&
    boundedText(value.query, 16_384) &&
    boundedText(value.hash, 8_192) &&
    (value.history === undefined || value.history === "push");
  const queryChangeRequest = (value) =>
    value &&
    typeof value === "object" &&
    Object.keys(value).length === 4 &&
    ["type", "runtime", "lifecycleId", "query"].every((key) =>
      Object.hasOwn(value, key),
    ) &&
    boundedText(value.runtime, 128) &&
    /^[a-z][a-z0-9-]*$/.test(value.runtime) &&
    Number.isSafeInteger(value.lifecycleId) &&
    value.lifecycleId > 0 &&
    boundedText(value.query, 16_384);
  const viewUrl = (root, view, source, routingQuery = "") => {
    const target = new URL(
      `${encodeURIComponent(view)}/`,
      new URL(root, location.href),
    );
    const current = new URL(source, location.href);
    target.search = current.search;
    target.hash = current.hash;
    for (const [key, value] of new URLSearchParams(routingQuery)) {
      if (!target.searchParams.has(key)) target.searchParams.set(key, value);
    }
    return target.toString();
  };
  const publicViewUrl = (view, query, hash) => {
    const target = new URL(
      `${encodeURIComponent(view)}/`,
      new URL(config.publicRootUrl, location.href),
    );
    const publicParameters = new URLSearchParams(query);
    for (const key of privateQueryKeys) publicParameters.delete(key);
    const parameters = new URLSearchParams(config.routingQuery);
    for (const key of new Set(parameters.keys())) publicParameters.delete(key);
    for (const [key, value] of publicParameters) parameters.append(key, value);
    parameters.delete("runtime");
    if (config.runtimeExplicit) parameters.set("runtime", config.runtime);
    target.search = parameters.toString();
    target.hash = hash;
    return target.toString();
  };
  const replayStorageKey = (view, source) => {
    if (!config.replayEnabled || typeof config.replayScope !== "string") {
      return undefined;
    }
    const url = new URL(source, location.href);
    const parameters = new URLSearchParams(url.search);
    for (const key of privateQueryKeys) parameters.delete(key);
    for (const key of new Set(new URLSearchParams(config.routingQuery).keys())) {
      parameters.delete(key);
    }
    parameters.sort();
    return [
      "marimo-studio:replay:v1",
      config.replayScope,
      encodeURIComponent(view),
      encodeURIComponent(config.runtime),
      encodeURIComponent(parameters.toString()),
    ].join(":");
  };
  const replayUrl = (value, view) => {
    if (!boundedText(value, 16_384)) return undefined;
    let url;
    try {
      url = new URL(value, location.href);
    } catch {
      return undefined;
    }
    const suffix = `/${encodeURIComponent(view)}/`;
    const capability = url.pathname.slice(
      config.replayPathPrefix.length,
      -suffix.length,
    );
    if (
      url.origin !== location.origin ||
      !url.pathname.startsWith(config.replayPathPrefix) ||
      !url.pathname.endsWith(suffix) ||
      !capability ||
      capability.includes("/") ||
      !/^s_[a-z0-9]{6}$/.test(url.searchParams.get("session_id") ?? "")
    ) return undefined;
    const current = new URL(location.href);
    const parameters = new URLSearchParams(config.routingQuery);
    const publicParameters = new URLSearchParams(current.search);
    for (const key of privateQueryKeys) publicParameters.delete(key);
    for (const key of new Set(parameters.keys())) publicParameters.delete(key);
    for (const [key, item] of publicParameters) parameters.append(key, item);
    parameters.delete("runtime");
    if (config.runtimeExplicit) parameters.set("runtime", config.runtime);
    parameters.set("session_id", url.searchParams.get("session_id"));
    parameters.set("marimo_studio_resume", "1");
    const candidate = new URL(url.pathname, location.origin);
    candidate.search = parameters.toString();
    candidate.hash = current.hash;
    return candidate;
  };
  const replayDocumentRequest = (value) => {
    if (
      !value ||
      typeof value !== "object" ||
      Object.keys(value).length !== 5 ||
      !["type", "runtime", "lifecycleId", "view", "url"].every((key) =>
        Object.hasOwn(value, key),
      ) ||
      value.type !== "marimo-studio:replay-document" ||
      !boundedText(value.runtime, 128) ||
      !/^[a-z][a-z0-9-]*$/.test(value.runtime) ||
      !Number.isSafeInteger(value.lifecycleId) ||
      value.lifecycleId <= 0 ||
      !allowedViews.has(value.view) ||
      !boundedText(value.url, 32 * 1_024) ||
      !childIdentity ||
      value.runtime !== childIdentity.runtime ||
      value.lifecycleId !== childIdentity.lifecycleId
    ) return undefined;
    return replayUrl(value.url, value.view);
  };
  const rememberReplay = (view, value) => {
    const key = replayStorageKey(view, location.href);
    const url = replayUrl(value, view);
    if (!key || !url) return;
    url.searchParams.delete("marimo_studio_resume");
    try {
      sessionStorage.setItem(key, url.toString());
    } catch {
      return;
    }
  };
  const chooseReplay = async () => {
    const key = replayStorageKey(config.view, location.href);
    if (!key) {
      loadFrame(config.fallbackUrl);
      return;
    }
    let stored;
    try {
      stored = sessionStorage.getItem(key);
    } catch {
      loadFrame(config.fallbackUrl);
      return;
    }
    const candidate = replayUrl(stored, config.view);
    if (!candidate) {
      loadFrame(config.fallbackUrl);
      return;
    }
    try {
      const response = await fetch(candidate, {
        cache: "no-store",
        credentials: "same-origin",
        method: "HEAD",
        redirect: "follow",
      });
      const responseUrl = new URL(response.url);
      const current =
        !response.redirected &&
        responseUrl.origin === candidate.origin &&
        responseUrl.pathname === candidate.pathname &&
        responseUrl.search === candidate.search &&
        response.status === 200 &&
        response.headers.get("cache-control")?.includes("no-store") &&
        response.headers.get("marimo-studio-revision") &&
        response.headers.get("marimo-studio-support-url");
      loadFrame(current ? candidate.toString() : config.fallbackUrl);
    } catch {
      loadFrame(config.fallbackUrl);
    }
  };
  const publicLocation = new URL(location.href);
  history.replaceState(
    history.state,
    "",
    publicViewUrl(config.view, publicLocation.search, publicLocation.hash),
  );
  currentSearch = location.search;
  addEventListener("message", (event) => {
    const type = messageType(event.data);
    if (
      event.source === frame?.contentWindow &&
      event.origin === "null" &&
      type &&
      childMessages.has(type)
    ) {
      if (type === "marimo-studio:query-change" && parent === window) {
        if (!queryChangeRequest(event.data)) return;
        history.replaceState(
          history.state,
          "",
          publicViewUrl(currentView, event.data.query, location.hash),
        );
        currentSearch = location.search;
        return;
      }
      if (type === "marimo-studio:navigate-view" && parent === window) {
        if (!navigationRequest(event.data)) return;
        if (event.data.history === "push") {
          currentView = event.data.view;
          history.pushState(
            history.state,
            "",
            publicViewUrl(event.data.view, event.data.query, event.data.hash),
          );
          currentSearch = location.search;
          return;
        }
        location.assign(
          publicViewUrl(event.data.view, event.data.query, event.data.hash),
        );
        return;
      }
      if (type === "marimo-studio:replay-document") {
        if (parent === window) {
          const candidate = replayDocumentRequest(event.data);
          if (candidate) {
            activeReplayUrl = candidate.toString();
            rememberReplay(event.data.view, candidate.toString());
          }
        }
        return;
      }
      if (type === "marimo-studio:view-ready" && parent === window) {
        childIdentity = {
          runtime: event.data.runtime,
          lifecycleId: event.data.lifecycleId,
        };
        rememberReplay(event.data.view, activeReplayUrl);
      }
      if (parent !== window) parent.postMessage(event.data, location.origin);
      return;
    }
    if (
      event.source !== parent ||
      event.origin !== location.origin ||
      !type ||
      !parentMessages.has(type)
    ) return;
    if (
      type === "marimo-studio:switch-view" &&
      !allowedViews.has(event.data.view)
    ) return;
    const message =
      type === "marimo-studio:switch-view"
        ? {
            ...event.data,
            documentUrl: viewUrl(
              config.internalRootUrl,
              event.data.view,
              event.data.documentUrl,
            ),
            supportUrl: viewUrl(
              new URL(
                "_marimo-studio/views/",
                new URL(config.internalRootUrl, location.href),
              ),
              event.data.view,
              event.data.supportUrl,
            ).replace(/\/$/, ""),
          }
        : event.data;
    frame?.contentWindow?.postMessage(message, "*");
  });
  if (typeof config.replayScope === "string") {
    addEventListener("pagehide", (event) => {
      documentClosed = true;
      if (!event.persisted) {
        frame?.remove();
        frameBlueprint?.remove();
      }
    });
    addEventListener("pageshow", (event) => {
      if (!event.persisted) return;
      documentClosed = false;
      if (!frame?.isConnected) location.reload();
    });
    addEventListener("popstate", () => {
      const targetView = [...allowedViews].find(
        (view) =>
          new URL(
            `${encodeURIComponent(view)}/`,
            new URL(config.publicRootUrl, location.href),
          ).pathname === location.pathname,
      );
      if (
        targetView === currentView &&
        location.search === currentSearch &&
        childIdentity
      ) {
        frame?.contentWindow?.postMessage(
          {
            type: "marimo-studio:restore-fragment",
            runtime: childIdentity.runtime,
            lifecycleId: childIdentity.lifecycleId,
            hash: location.hash,
          },
          "*",
        );
        return;
      }
      location.reload();
    });
    void chooseReplay();
  }
})();
"""


def isolated_presentation_document(
    *,
    child_url: str,
    internal_root_url: str,
    public_root_url: str,
    routing_query: str,
    view_name: str,
    views: Sequence[str],
    private_query_keys: Sequence[str],
    runtime: str,
    runtime_explicit: bool,
    replay_enabled: bool = False,
    replay_scope: str | None = None,
    title_text: str,
    nonce: str,
) -> str:
    """Return a trusted wrapper around one opaque-origin authored document."""
    config = json.dumps(
        {
            "internalRootUrl": internal_root_url,
            "publicRootUrl": public_root_url,
            "routingQuery": routing_query,
            "view": view_name,
            "views": list(views),
            "privateQueryKeys": list(private_query_keys),
            "fallbackUrl": child_url,
            "replayPathPrefix": public_root_url.rstrip("/")
            + "/_marimo-studio/presentation/d.",
            "replayEnabled": replay_enabled,
            "replayScope": replay_scope,
            "runtime": runtime,
            "runtimeExplicit": runtime_explicit,
        },
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    bridge = _BRIDGE.replace("CONFIG", config, 1)
    frame_allow = "clipboard-write"
    frame_host: Node = (
        cast(
            Node,
            iframe(
                id="marimo-studio-presentation",
                src=child_url,
                title=title_text,
                sandbox=PRESENTATION_SANDBOX,
                allow=frame_allow,
            ),
        )
        if replay_scope is None
        else cast(
            Node,
            div(
                id="marimo-studio-presentation",
                data_marimo_studio_frame_blueprint="",
                data_frame_title=title_text,
                data_frame_sandbox=PRESENTATION_SANDBOX,
                data_frame_allow=frame_allow,
            ),
        )
    )
    return render(
        cast(
            Node,
            html(lang="en", data_marimo_studio_preview_state="ready")[
                node_list(
                    head[
                        node_list(
                            meta(charset="utf-8"),
                            meta(
                                name="viewport",
                                content="width=device-width, initial-scale=1",
                            ),
                            title[title_text],
                            style(nonce=nonce)[
                                Markup(
                                    "html,body{height:100%;margin:0;overflow:hidden}"
                                    "#marimo-studio-presentation{border:0;display:block;"
                                    "height:100%;width:100%}"
                                )
                            ],
                        )
                    ],
                    body[
                        node_list(
                            div(id="marimo-runtime-root", hidden=True),
                            frame_host,
                            script(nonce=nonce)[Markup(bridge)],
                        )
                    ],
                )
            ],
        )
    )


def isolation_content_security_policy(nonce: str) -> str:
    """Return the wrapper policy that admits its frame and bridge."""
    return (
        "default-src 'none'; "
        "base-uri 'none'; "
        "connect-src 'self'; "
        "form-action 'none'; "
        "frame-src 'self'; "
        f"script-src 'nonce-{nonce}'; "
        f"style-src 'nonce-{nonce}'"
    )
