import type { RuntimeConfig } from "../runtime-config";
import type { ProjectionResolution, ResolvedProjection } from "./resolution";

import { createProjectionInventory } from "./resolution";
import { notifyProjectionResolutionStale } from "./staleness.ts";

const SYMBOLIC_METADATA = [
  "data-marimo-producer-ref",
  "data-marimo-projection-kind",
  "data-marimo-projection-target",
  "data-marimo-projection-variable",
  "data-marimo-studio-instance",
] as const;

const RUNTIME_METADATA = [
  ...SYMBOLIC_METADATA,
  "data-marimo-diagnostic-code",
  "data-marimo-diagnostic-hint",
  "data-marimo-diagnostic-message",
  "data-marimo-error",
  "data-marimo-error-code",
  "data-marimo-selector",
  "data-marimo-variable",
  "data-output-mime",
  "data-output-mimes",
  "data-runtime-cell-id",
  "data-marimo-lens-cell-id",
  "data-marimo-lens-selector",
] as const;

// Keep consumer-authored labels while releasing metadata owned by this projection.
const projectionDescriptions = new WeakMap<HTMLElement, Map<string, string>>();
const publishProjectionDescription = (host: HTMLElement, projection?: ResolvedProjection): void => {
  const producer = projection?.producerLabel ?? projection?.runtimeCellId;
  const kind = projection?.request.kind;
  let detail: string | undefined;
  if (kind === "cell") detail = "Cell";
  else if (kind)
    detail = `${kind === "value" ? "Value" : "Output"}${producer ? ` · ${producer}` : ""}`;
  const previous = projectionDescriptions.get(host);
  const published = new Map<string, string>();
  for (const [attribute, value] of [
    ["data-marimo-lens-label", projection?.request.target],
    ["data-marimo-lens-detail", detail],
    ["data-marimo-lens-render-source", projection && JSON.stringify(projection.site.source)],
  ] as const) {
    const current = host.getAttribute(attribute);
    if (current !== null && current !== previous?.get(attribute)) continue;
    if (value === undefined) host.removeAttribute(attribute);
    else {
      if (current !== value) host.setAttribute(attribute, value);
      published.set(attribute, value);
    }
  }
  if (published.size) projectionDescriptions.set(host, published);
  else projectionDescriptions.delete(host);
};

/** Publish the same resolved cell to native renderers and the Lens DOM contract. */
export const setProjectionRuntimeCell = (
  host: HTMLElement,
  cellId: string | null | undefined,
): void => {
  if (cellId) {
    host.dataset.runtimeCellId = cellId;
    host.dataset.marimoLensCellId = cellId;
  } else {
    delete host.dataset.runtimeCellId;
    delete host.dataset.marimoLensCellId;
  }
};

const clearAttributes = (host: HTMLElement, attributes: readonly string[]): void => {
  attributes.forEach((attribute) => host.removeAttribute(attribute));
};

export const resetProjectionHostMetadata = (host: HTMLElement): void => {
  publishProjectionDescription(host);
  clearAttributes(host, RUNTIME_METADATA);
};

export const mountedResolvedProjections = (
  config: RuntimeConfig,
  root: ParentNode = document,
): readonly ResolvedProjection[] => {
  const inventory = createProjectionInventory(config, root);
  return inventory.hosts.flatMap((host) => {
    const { resolution } = inventory.resolve(host);
    applyProjectionMetadata(host, resolution, config.projectionRevision);
    return resolution.ok ? [resolution.value] : [];
  });
};

export const applyProjectionMetadata = (
  host: Element,
  resolution: ProjectionResolution,
  projectionRevision: string,
): void => {
  if (!(host instanceof HTMLElement)) {
    return;
  }
  const previousProducer = host.dataset.marimoProducerRef;
  clearAttributes(host, SYMBOLIC_METADATA);
  delete host.dataset.marimoLensSelector;
  const request = resolution.ok ? resolution.value.request : resolution.error;
  host.dataset.marimoStudioInstance = request.instanceId;
  if (!resolution.ok) {
    setProjectionRuntimeCell(host, undefined);
    publishProjectionDescription(host);
    return;
  }
  if (resolution.value.bindingsStale) {
    notifyProjectionResolutionStale(projectionRevision);
  }
  const kind = resolution.value.request.kind;
  publishProjectionDescription(host, resolution.value);
  if (resolution.value.runtimeCellId !== undefined) {
    setProjectionRuntimeCell(host, resolution.value.runtimeCellId);
  } else if (previousProducer !== resolution.value.producer) {
    setProjectionRuntimeCell(host, undefined);
  }
  if (kind === "value" || kind === "output")
    host.dataset.marimoLensSelector = resolution.value.request.target;
  host.dataset.marimoProducerRef = resolution.value.producer;
  host.dataset.marimoProjectionKind = resolution.value.request.kind;
  host.dataset.marimoProjectionTarget = resolution.value.request.target;
  if (resolution.value.variable === null) {
    delete host.dataset.marimoProjectionVariable;
  } else {
    host.dataset.marimoProjectionVariable = resolution.value.variable;
  }
};
