import type { MountConfig, RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import {
  DOCUMENT_LIFECYCLE_QUERY_PARAM,
  STUDIO_CLIENT_QUERY_PARAM,
} from "@marimo-studio/protocol/query";

import { getMountConfig } from "../runtime-config/index.ts";
import { setEditorBindingQuery } from "./view-navigation.ts";

export const presentationRefreshUrl = (
  config: Pick<RuntimeConfig, "presentationSessionId" | "supportUrl" | "view">,
  currentHref = globalThis.location.href,
  runtimeSessionId?: string,
  mount: Pick<
    MountConfig,
    "clientId" | "lifecycleId" | "renewalToken" | "runtime" | "runtimeSessionId"
  > = getMountConfig(),
): string => {
  const support = new URL(config.supportUrl, currentHref);
  const presentationMarker = "/_marimo-studio/presentation/";
  const presentationBoundary = support.pathname.lastIndexOf(presentationMarker);
  const supportMarker = "/_marimo-studio/views/";
  const supportBoundary = support.pathname.lastIndexOf(supportMarker);
  if (presentationBoundary < 0 || supportBoundary < 0) {
    return currentHref;
  }
  const current = new URL(currentHref);
  const currentPresentationBoundary = current.pathname.lastIndexOf(presentationMarker);
  const currentCapability =
    currentPresentationBoundary < 0
      ? ""
      : current.pathname.slice(currentPresentationBoundary + presentationMarker.length);
  const currentToken = currentCapability.split("/", 1)[0];
  const renewalToken =
    mount.renewalToken ??
    (currentToken.startsWith("d.")
      ? currentToken
      : current.searchParams.get("marimo_studio_renewal"));
  if (!renewalToken?.startsWith("d.")) {
    return currentHref;
  }
  const prefix = support.pathname.slice(0, presentationBoundary + presentationMarker.length);
  const target = new URL(
    `${prefix}${renewalToken}/${encodeURIComponent(config.view)}/`,
    support.origin,
  );
  target.search = current.search;
  target.searchParams.delete("marimo_studio_renewal");
  target.searchParams.delete("session_id");
  target.searchParams.delete(STUDIO_CLIENT_QUERY_PARAM);
  target.searchParams.delete(DOCUMENT_LIFECYCLE_QUERY_PARAM);
  if (mount.clientId && mount.lifecycleId) {
    target.searchParams.set(STUDIO_CLIENT_QUERY_PARAM, mount.clientId);
    target.searchParams.set(DOCUMENT_LIFECYCLE_QUERY_PARAM, String(mount.lifecycleId));
  }
  const nativeSession =
    mount.runtime === "server" ? (mount.runtimeSessionId ?? runtimeSessionId) : undefined;
  if (mount.runtime === "server" && nativeSession) {
    target.searchParams.set("session_id", nativeSession);
  }
  support.searchParams.forEach((value, key) => {
    if (!target.searchParams.has(key)) {
      target.searchParams.set(key, value);
    }
  });
  setEditorBindingQuery(target, mount.clientId, config.supportUrl);
  target.hash = current.hash;
  return target.href;
};

export const presentationRenewalSupportUrl = (
  documentUrl: string,
  supportUrl: string,
  currentHref = globalThis.location.href,
): string => {
  const document = new URL(documentUrl, currentHref);
  const support = new URL(supportUrl, currentHref);
  const presentationMarker = "/_marimo-studio/presentation/";
  const presentationBoundary = document.pathname.lastIndexOf(presentationMarker);
  const supportMarker = "/_marimo-studio/views/";
  const supportBoundary = support.pathname.lastIndexOf(supportMarker);
  if (presentationBoundary < 0 || supportBoundary < 0) {
    return support.href;
  }
  const capability = document.pathname
    .slice(presentationBoundary + presentationMarker.length)
    .split("/", 1)[0];
  if (!capability?.startsWith("d.")) {
    return support.href;
  }
  const view = support.pathname.slice(supportBoundary + supportMarker.length).split("/", 1)[0];
  if (!view) {
    return support.href;
  }
  const prefix = document.pathname.slice(0, presentationBoundary + presentationMarker.length);
  const target = new URL(
    `${prefix}${capability}${supportMarker}${encodeURIComponent(decodeURIComponent(view))}`,
    document.origin,
  );
  target.search = support.search;
  return target.href;
};
