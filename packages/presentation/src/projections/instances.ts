import type { ObservedProjectionInstance } from "@marimo-studio/protocol/projections";

import type { RuntimeConfig } from "../runtime-config";
import type { ProjectionResolution, ResolvedProjection } from "./resolution";

import { getRuntimeConfig, hasRuntimeConfig } from "../runtime-config";
import {
  projectionKindForHost,
  projectionRequestForHost,
  projectionTargetForHost,
} from "./identity";
import { createProjectionResolutionContext, resolveHostProjection } from "./resolution";

const STATES: readonly ObservedProjectionInstance["phase"][] = [
  "connecting",
  "loading",
  "stale",
  "ready",
  "missing",
  "error",
];

const isProjectionState = (value: string): value is ObservedProjectionInstance["phase"] =>
  STATES.some((state) => state === value);

const SYMBOLIC_METADATA = [
  "data-marimo-producer-ref",
  "data-marimo-projection-kind",
  "data-marimo-projection-target",
  "data-marimo-projection-variable",
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
] as const;

const clearAttributes = (host: HTMLElement, attributes: readonly string[]): void => {
  attributes.forEach((attribute) => host.removeAttribute(attribute));
};

export const resetProjectionHostMetadata = (host: HTMLElement): void => {
  clearAttributes(host, RUNTIME_METADATA);
};

const hostState = (host: Element, failed: boolean): ObservedProjectionInstance["phase"] => {
  if (failed) {
    return "error";
  }
  const state = host instanceof HTMLElement ? host.dataset.state : undefined;
  return state !== undefined && isProjectionState(state) ? state : "connecting";
};

export const mountedResolvedProjections = (
  config: RuntimeConfig,
  root: ParentNode = document,
): readonly ResolvedProjection[] => {
  const context = createProjectionResolutionContext(config, root);
  return context.hosts().flatMap((host) => {
    const kind = projectionKindForHost(host);
    const resolution = resolveHostProjection(
      config,
      host,
      projectionRequestForHost(host, kind, projectionTargetForHost(host, kind)),
      context,
    );
    applyProjectionMetadata(host, resolution);
    return resolution.ok ? [resolution.value] : [];
  });
};

export const applyProjectionMetadata = (host: Element, resolution: ProjectionResolution): void => {
  if (!(host instanceof HTMLElement)) {
    return;
  }
  clearAttributes(host, SYMBOLIC_METADATA);
  if (!resolution.ok) {
    return;
  }
  host.dataset.marimoProducerRef = resolution.value.producer;
  host.dataset.marimoProjectionKind = resolution.value.request.kind;
  host.dataset.marimoProjectionTarget = resolution.value.request.target;
  if (resolution.value.variable === null) {
    delete host.dataset.marimoProjectionVariable;
  } else {
    host.dataset.marimoProjectionVariable = resolution.value.variable;
  }
};

export const renderedProjectionInstances = (
  root: ParentNode = document,
): readonly ObservedProjectionInstance[] => {
  if (!hasRuntimeConfig()) {
    return [];
  }
  const config = getRuntimeConfig();
  const context = createProjectionResolutionContext(config, root);
  const hosts = context.hosts().slice(0, config.projectionPolicy.maxActiveInstances + 1);
  return hosts.map((host) => {
    const kind = projectionKindForHost(host);
    const target = projectionTargetForHost(host, kind);
    const request = projectionRequestForHost(host, kind, target);
    const resolution = resolveHostProjection(config, host, request, context);
    applyProjectionMetadata(host, resolution);
    if (!resolution.ok) {
      return {
        mountId: request.siteId || null,
        instanceId: request.instanceId,
        target,
        runtimeCellId: null,
        phase: hostState(host, true),
        error: {
          code: resolution.error.code,
          message: resolution.error.message,
        },
      } satisfies ObservedProjectionInstance;
    }
    const phase = hostState(host, false);
    const metadata = host instanceof HTMLElement ? host.dataset : undefined;
    const error =
      phase === "error" || phase === "missing"
        ? {
            code: metadata?.marimoDiagnosticCode ?? "projection-host-failed",
            message: metadata?.marimoDiagnosticMessage ?? "The mounted projection host failed.",
          }
        : null;
    return {
      mountId: resolution.value.site.id,
      instanceId: request.instanceId,
      target,
      runtimeCellId: resolution.value.runtimeCellId ?? null,
      phase,
      error,
    } satisfies ObservedProjectionInstance;
  });
};
