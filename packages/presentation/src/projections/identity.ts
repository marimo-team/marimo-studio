import type { ProjectionKind, ProjectionRequest } from "@marimo-studio/protocol/projections";

import type { RuntimeProjectionRequest } from "./resolution.ts";

const instanceIds = new WeakMap<Element, string>();
let nextInstanceId = 1;

export const PROJECTION_SITE_ATTRIBUTE = "data-marimo-studio-site";
export const PROJECTION_PRESERVE_ATTRIBUTE = "data-marimo-studio-preserve";

export const projectionKindForHost = (host: Element): ProjectionKind => {
  if (host.localName === "marimo-cell") {
    return "cell";
  }
  return host.localName === "marimo-output" ? "output" : "value";
};

export const projectionTargetForHost = (
  host: Element,
  kind: ProjectionKind = projectionKindForHost(host),
): string => {
  if (kind === "cell") {
    return host.getAttribute("name")?.trim() ?? "";
  }
  if (kind === "output") {
    return host.getAttribute("value")?.trim() ?? "";
  }
  return host.getAttribute("mo-value")?.trim() ?? "";
};

export const projectionInstanceId = (host: Element): string => {
  const current = instanceIds.get(host);
  if (current !== undefined) {
    return current;
  }
  const created = `projection-${nextInstanceId++}`;
  instanceIds.set(host, created);
  return created;
};

export const projectionRequestForHost = (
  host: Element,
  kind: ProjectionKind,
  target: string,
): RuntimeProjectionRequest => ({
  siteId: host.getAttribute(PROJECTION_SITE_ATTRIBUTE)?.trim() ?? "",
  instanceId: projectionInstanceId(host),
  kind,
  target,
});

export const projectionWireRequest = (
  request: ProjectionRequest | RuntimeProjectionRequest,
): ProjectionRequest => ({
  siteId: request.siteId,
  instanceId: request.instanceId,
  target: request.target,
});
