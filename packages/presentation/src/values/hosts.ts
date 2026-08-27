import type { ValueReadError } from "@marimo-studio/protocol/value-read";

import { z } from "zod";

import type { RuntimeProjectionRequest as ProjectionRequest } from "../projections/resolution";

import { syncProjectionHostAttributes } from "../cells/host.ts";
import { isArtifactProjectionHost } from "../projections/artifact-host.ts";
import { notifyProjectionChanged } from "../projections/changes.ts";
import { PROJECTION_SITE_ATTRIBUTE, projectionRequestForHost } from "../projections/identity.ts";
import { applyProjectionMetadata, resetProjectionHostMetadata } from "../projections/instances.ts";
import {
  createProjectionResolutionContext,
  type ProjectionResolutionContext,
  type ResolvedProjection,
  resolveHostProjection,
} from "../projections/resolution.ts";
import {
  getRuntimeConfig,
  getRuntimeProjectionConfig,
  type JsonValue,
  type ProjectionDiagnostic,
  subscribeRuntimeProjectionConfig,
} from "../runtime-config/index.ts";
import { type ValuePhase, ValueStates } from "./state.ts";

const ATTRIBUTE = "mo-value";
const ATTRIBUTE_SELECTOR = `[${ATTRIBUTE}]`;
const PRESERVED_ID_PREFIX = "marimo-studio-value-";
const textValueSchema = z.union([z.string(), z.number(), z.boolean()]);
const hosts = new Set<HTMLElement>();
const renderedValues = new WeakMap<
  HTMLElement,
  { readonly selector: string; readonly fingerprint: string }
>();
interface ProjectedValue {
  readonly fingerprint: string;
  readonly text: string;
  readonly value: JsonValue;
}

const cachedValues = new Map<string, ProjectedValue>();
const hostValues = new WeakMap<HTMLElement, JsonValue>();
const preparedHosts = new WeakSet<HTMLElement>();
const hostSelectors = new WeakMap<HTMLElement, string>();
interface HostProjection {
  readonly projection: ResolvedProjection;
  readonly projectionRevision: string;
}

let hostProjections = new WeakMap<HTMLElement, HostProjection>();
const runtimeCellIds = new Map<string, string>();
const projectionListeners = new Set<() => void>();
let projectionSnapshot: readonly ValueHostProjection[] = [];
const states = new ValueStates();
let cacheProjectionRevision: string | undefined;
let observer: MutationObserver | undefined;
let unsubscribeConfig: (() => void) | undefined;
let configurePending = false;
let started = false;

export interface MarimoValueHost extends HTMLElement {
  readonly marimoValue: JsonValue | undefined;
}

export interface MarimoValueUpdatedDetail {
  readonly selector: string;
  readonly value: JsonValue;
}

export interface MarimoValueErrorDetail {
  readonly selector: string;
  readonly code: string;
  readonly message: string;
  readonly hint?: string;
}

export interface ValueHostProjection {
  readonly host: HTMLElement;
  readonly projection: ResolvedProjection;
  readonly request: ProjectionRequest;
  readonly projectionRevision: string;
}

declare global {
  interface DocumentEventMap {
    "marimo-value-error": CustomEvent<MarimoValueErrorDetail>;
    "marimo-value-updated": CustomEvent<MarimoValueUpdatedDetail>;
  }

  interface HTMLElementEventMap {
    "marimo-value-error": CustomEvent<MarimoValueErrorDetail>;
    "marimo-value-updated": CustomEvent<MarimoValueUpdatedDetail>;
  }
}

export const isMarimoValueHost = (host: HTMLElement): host is MarimoValueHost =>
  Object.getOwnPropertyDescriptor(host, "marimoValue")?.get instanceof Function;

const prepareHost = (host: HTMLElement): MarimoValueHost => {
  if (!preparedHosts.has(host)) {
    Object.defineProperty(host, "marimoValue", {
      configurable: true,
      enumerable: false,
      get: () => hostValues.get(host),
    });
    preparedHosts.add(host);
  }
  if (!isMarimoValueHost(host)) {
    throw new Error("Unable to expose the projected value on its host element");
  }
  return host;
};

const clearHostValue = (host: HTMLElement): void => {
  prepareHost(host);
  hostValues.delete(host);
};

const setHostValue = (host: HTMLElement, value: JsonValue): JsonValue => {
  const snapshot = structuredClone(value);
  hostValues.set(prepareHost(host), snapshot);
  return snapshot;
};

const selectorFor = (host: HTMLElement): string => {
  return host.getAttribute(ATTRIBUTE)?.trim() ?? "";
};

const prepareValueHost = (host: HTMLElement): void => {
  if (!isArtifactProjectionHost(host)) {
    return;
  }
  const siteId = host.getAttribute(PROJECTION_SITE_ATTRIBUTE)?.trim();
  if (!siteId) {
    return;
  }
  if (!host.id) {
    const id = `${PRESERVED_ID_PREFIX}${siteId}`;
    const existing = host.ownerDocument.getElementById(id);
    if (existing === null || existing === host) {
      host.id = id;
    }
  }
  if (host.id) {
    host.setAttribute("data-hx-preserve", "");
  }
};

export const prepareValueHosts = (root: ParentNode): void => {
  root.querySelectorAll<HTMLElement>(ATTRIBUTE_SELECTOR).forEach(prepareValueHost);
};

export const syncPreservedValueHosts = (source: ParentNode, live: Document): void => {
  source
    .querySelectorAll<HTMLElement>(`${ATTRIBUTE_SELECTOR}[data-hx-preserve][id]`)
    .forEach((host) => {
      if (!isArtifactProjectionHost(host)) {
        return;
      }
      const preserved = live.getElementById(host.id);
      if (preserved?.localName === host.localName && preserved !== host) {
        syncProjectionHostAttributes(preserved, host);
      }
    });
};

const diagnosticFor = (selector: string, siteId?: string): ProjectionDiagnostic | undefined => {
  return getRuntimeConfig().diagnostics.find(
    (diagnostic) =>
      diagnostic.projection === "value" &&
      diagnostic.target === selector &&
      (diagnostic.siteId === undefined || diagnostic.siteId === siteId),
  );
};

const publishHostProjections = (): void => {
  projectionSnapshot = Array.from(hosts).flatMap((host) => {
    const current = hostProjections.get(host);
    return current === undefined
      ? []
      : [
          {
            host,
            projection: current.projection,
            request: current.projection.request,
            projectionRevision: current.projectionRevision,
          },
        ];
  });
  projectionListeners.forEach((listener) => listener());
};

const clearHostDiagnostic = (host: HTMLElement) => {
  delete host.dataset.marimoError;
  delete host.dataset.marimoErrorCode;
  delete host.dataset.marimoDiagnosticCode;
  delete host.dataset.marimoDiagnosticMessage;
  delete host.dataset.marimoDiagnosticHint;
  if ("marimoStudioTitle" in host.dataset) {
    host.removeAttribute("title");
    delete host.dataset.marimoStudioTitle;
  }
  if ("marimoStudioAriaLabel" in host.dataset) {
    host.removeAttribute("aria-label");
    delete host.dataset.marimoStudioAriaLabel;
  }
  if ("marimoStudioTabindex" in host.dataset) {
    host.removeAttribute("tabindex");
    delete host.dataset.marimoStudioTabindex;
  }
  if ("marimoStudioRole" in host.dataset) {
    host.removeAttribute("role");
    delete host.dataset.marimoStudioRole;
  }
  if ("marimoStudioValueFallback" in host.dataset) {
    host.textContent = "";
    delete host.dataset.marimoStudioValueFallback;
  }
};

const resetValueHost = (host: HTMLElement): void => {
  clearHostDiagnostic(host);
  resetProjectionHostMetadata(host);
  renderedValues.delete(host);
  clearHostValue(host);
  host.textContent = "";
  setState(host, "connecting");
};

const selectorHasOwner = (selector: string): boolean =>
  Array.from(hosts).some((host) => {
    const current = hostProjections.get(host);
    return (
      current?.projectionRevision === cacheProjectionRevision &&
      current?.projection.request.target === selector
    );
  });

const evictUnownedSelector = (selector: string | undefined): void => {
  if (selector === undefined || selectorHasOwner(selector)) {
    return;
  }
  cachedValues.delete(selector);
  runtimeCellIds.delete(selector);
  states.clear(selector);
};

const synchronizeProjectionRevision = (projectionRevision: string): void => {
  if (cacheProjectionRevision === projectionRevision) {
    return;
  }
  cacheProjectionRevision = projectionRevision;
  cachedValues.clear();
  runtimeCellIds.clear();
  states.clearAll();
  hostProjections = new WeakMap();
  hosts.forEach(resetValueHost);
  publishHostProjections();
};

const setState = (host: HTMLElement, state: ValuePhase): boolean => {
  const previous = host.dataset.state;
  host.dataset.state = state;
  if (["connecting", "loading", "stale"].includes(state)) {
    host.setAttribute("aria-busy", "true");
  } else {
    host.removeAttribute("aria-busy");
  }
  notifyProjectionChanged();
  return previous !== state;
};

const failHost = (host: HTMLElement, error: ValueReadError, diagnostic?: ProjectionDiagnostic) => {
  clearHostValue(host);
  const hint = diagnostic?.hint || error.hint;
  host.dataset.marimoError = error.message;
  host.dataset.marimoErrorCode = error.code;
  host.dataset.marimoDiagnosticCode = error.code;
  host.dataset.marimoDiagnosticMessage = error.message;
  if (hint) {
    host.dataset.marimoDiagnosticHint = hint;
  } else {
    delete host.dataset.marimoDiagnosticHint;
  }
  if (!host.hasAttribute("title") || "marimoStudioTitle" in host.dataset) {
    host.title = hint ? `${error.message} ${hint}` : error.message;
    host.dataset.marimoStudioTitle = "";
  }
  const description = hint ? `${error.message} ${hint}` : error.message;
  if (!host.hasAttribute("aria-label") || "marimoStudioAriaLabel" in host.dataset) {
    host.setAttribute("aria-label", description);
    host.dataset.marimoStudioAriaLabel = "";
  }
  if (!host.hasAttribute("tabindex")) {
    host.tabIndex = 0;
    host.dataset.marimoStudioTabindex = "";
  }
  if (!host.hasAttribute("role")) {
    host.setAttribute("role", "status");
    host.dataset.marimoStudioRole = "";
  }
  const detail: MarimoValueErrorDetail = hint
    ? { selector: selectorFor(host), code: error.code, message: error.message, hint }
    : { selector: selectorFor(host), code: error.code, message: error.message };
  if (setState(host, "error")) {
    host.dispatchEvent(
      new CustomEvent<MarimoValueErrorDetail>("marimo-value-error", {
        bubbles: true,
        composed: true,
        detail,
      }),
    );
  }
};

const clearProjectedValue = (host: HTMLElement) => {
  renderedValues.delete(host);
  clearHostValue(host);
  const config = getRuntimeConfig();
  host.textContent = config.dev || config.mode === "edit" ? "Unavailable" : "";
  host.dataset.marimoStudioValueFallback = "";
};

const visit = (node: Node, callback: (host: HTMLElement) => void) => {
  if (!(node instanceof Element)) {
    return;
  }
  if (node instanceof HTMLElement && node.matches(ATTRIBUTE_SELECTOR)) {
    callback(node);
  }
  node.querySelectorAll<HTMLElement>(ATTRIBUTE_SELECTOR).forEach(callback);
};

const projectValue = (value: JsonValue): ProjectedValue => {
  const fingerprint = JSON.stringify(value);
  if (value === null) {
    return { fingerprint, text: "", value };
  }
  const textValue = textValueSchema.safeParse(value);
  if (textValue.success) {
    return { fingerprint, text: String(textValue.data), value };
  }
  return { fingerprint, text: fingerprint, value };
};

const renderHost = (
  host: HTMLElement,
  selector: string,
  projection: ProjectedValue,
  phase: ValuePhase = "ready",
) => {
  clearHostDiagnostic(host);
  const rendered = renderedValues.get(host);
  const changed =
    rendered?.selector !== selector || rendered.fingerprint !== projection.fingerprint;
  const snapshot = setHostValue(host, projection.value);
  if (!changed) {
    setState(host, phase);
    return;
  }
  host.textContent = projection.text;
  renderedValues.set(host, { selector, fingerprint: projection.fingerprint });
  setState(host, "ready");
  const detail: MarimoValueUpdatedDetail = { selector, value: snapshot };
  host.dispatchEvent(
    new CustomEvent<MarimoValueUpdatedDetail>("marimo-value-updated", {
      bubbles: true,
      composed: true,
      detail,
    }),
  );
  if (phase !== "ready") {
    setState(host, phase);
  }
};

const connectHost = (
  host: HTMLElement,
  context: ProjectionResolutionContext = createProjectionResolutionContext(
    getRuntimeProjectionConfig(),
    document,
  ),
) => {
  if (!isArtifactProjectionHost(host)) {
    return;
  }
  prepareValueHost(host);
  prepareHost(host);
  hosts.add(host);
  const selector = selectorFor(host);
  hostSelectors.set(host, selector);
  const config = getRuntimeProjectionConfig();
  synchronizeProjectionRevision(config.projectionRevision);
  const request = projectionRequestForHost(host, "value", selector);
  const resolution = resolveHostProjection(config, host, request, context);
  applyProjectionMetadata(host, resolution);
  if (!resolution.ok) {
    hostProjections.delete(host);
    delete host.dataset.marimoSelector;
    delete host.dataset.marimoVariable;
    delete host.dataset.runtimeCellId;
    const diagnostic = diagnosticFor(selector, request.siteId);
    clearProjectedValue(host);
    failHost(
      host,
      {
        code: diagnostic?.code ?? resolution.error.code,
        message: diagnostic?.message ?? resolution.error.message,
      },
      diagnostic,
    );
    evictUnownedSelector(selector);
    publishHostProjections();
    return;
  }
  const projection = resolution.value;
  hostProjections.set(host, { projection, projectionRevision: config.projectionRevision });
  clearHostDiagnostic(host);
  host.dataset.marimoSelector = selector;
  host.dataset.marimoVariable = projection.variable ?? "";
  const runtimeCellId = projection.runtimeCellId ?? runtimeCellIds.get(selector);
  if (runtimeCellId) {
    host.dataset.runtimeCellId = runtimeCellId;
  } else {
    delete host.dataset.runtimeCellId;
  }
  const cached = cachedValues.get(selector);
  const state = states.connected(selector, cached !== undefined);
  if (state.phase === "error" && state.error) {
    failHost(host, state.error);
  } else if (cached) {
    renderHost(host, selector, cached, state.phase);
  } else {
    clearHostValue(host);
    setState(host, state.phase);
  }
  publishHostProjections();
};

const disconnectHost = (host: HTMLElement) => {
  const selector = hostSelectors.get(host);
  hosts.delete(host);
  hostProjections.delete(host);
  evictUnownedSelector(selector);
  resetValueHost(host);
  publishHostProjections();
};

const releaseHost = (host: HTMLElement) => {
  if (!hosts.has(host)) {
    return;
  }
  disconnectHost(host);
  hostValues.delete(host);
  hostSelectors.delete(host);
  if (preparedHosts.delete(host)) {
    Reflect.deleteProperty(host, "marimoValue");
  }
  delete host.dataset.state;
  host.removeAttribute("aria-busy");
  notifyProjectionChanged();
};

const reconcileHosts = () => {
  if (!started) {
    return;
  }
  hosts.forEach((host) => {
    if (!host.isConnected || !host.matches(ATTRIBUTE_SELECTOR) || !isArtifactProjectionHost(host)) {
      releaseHost(host);
    }
  });
  const context = createProjectionResolutionContext(getRuntimeProjectionConfig(), document);
  visit(document.documentElement, (host) => connectHost(host, context));
};

const configure = () => {
  synchronizeProjectionRevision(getRuntimeProjectionConfig().projectionRevision);
  if (configurePending) {
    return;
  }
  configurePending = true;
  queueMicrotask(() => {
    configurePending = false;
    reconcileHosts();
  });
};

export const startValueHosts = () => {
  started = true;
  reconcileHosts();
  observer?.disconnect();
  observer = new MutationObserver((records) => {
    const context = createProjectionResolutionContext(getRuntimeProjectionConfig(), document);
    const changedHosts = new Set<HTMLElement>();
    const movedHosts = new Set<HTMLElement>();
    for (const record of records) {
      if (record.type === "attributes") {
        if (record.target instanceof HTMLElement) {
          changedHosts.add(record.target);
        }
        continue;
      }
      record.removedNodes.forEach((node) => visit(node, (host) => movedHosts.add(host)));
      record.addedNodes.forEach((node) => visit(node, (host) => movedHosts.add(host)));
    }
    movedHosts.forEach((host) => {
      const connected =
        host.isConnected && host.matches(ATTRIBUTE_SELECTOR) && isArtifactProjectionHost(host);
      if (connected && !hosts.has(host)) {
        connectHost(host, context);
      } else if (!connected && hosts.has(host)) {
        releaseHost(host);
      }
    });
    changedHosts.forEach((host) => {
      if (!host.isConnected || !isArtifactProjectionHost(host)) {
        releaseHost(host);
        return;
      }
      const attribute = host.getAttribute(ATTRIBUTE);
      const nextSelector = attribute === null ? null : attribute.trim();
      const nextSiteId = host.getAttribute(PROJECTION_SITE_ATTRIBUTE)?.trim() ?? "";
      const current = hostProjections.get(host)?.projection.request;
      if (nextSelector === hostSelectors.get(host) && nextSiteId === current?.siteId) {
        return;
      }
      releaseHost(host);
      if (nextSelector !== null) {
        connectHost(host, context);
      }
    });
  });
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: [ATTRIBUTE, PROJECTION_SITE_ATTRIBUTE],
    childList: true,
    subtree: true,
  });
  unsubscribeConfig?.();
  unsubscribeConfig = subscribeRuntimeProjectionConfig(configure);
};

export const stopValueHosts = () => {
  started = false;
  observer?.disconnect();
  observer = undefined;
  unsubscribeConfig?.();
  unsubscribeConfig = undefined;
  hosts.forEach((host) => {
    resetValueHost(host);
    delete host.dataset.state;
    host.removeAttribute("aria-busy");
  });
  hosts.clear();
  hostProjections = new WeakMap();
  publishHostProjections();
  runtimeCellIds.clear();
  cachedValues.clear();
  states.clearAll();
  cacheProjectionRevision = undefined;
};

export const getValueHostProjections = (): readonly ValueHostProjection[] => projectionSnapshot;

export const getValueHosts = (): readonly HTMLElement[] => Array.from(hosts);

export const subscribeValueHostProjections = (listener: () => void): (() => void) => {
  projectionListeners.add(listener);
  return () => projectionListeners.delete(listener);
};

export const setValueRuntimeCell = (
  selectors: readonly string[],
  cellId: string | null,
  projectionRevision: string,
): void => {
  if (projectionRevision !== cacheProjectionRevision) {
    return;
  }
  selectors.forEach((selector) => {
    if (cellId) {
      runtimeCellIds.set(selector, cellId);
    } else {
      runtimeCellIds.delete(selector);
    }
  });
  hosts.forEach((host) => {
    if (!selectors.includes(selectorFor(host))) return;
    if (cellId) {
      host.dataset.runtimeCellId = cellId;
    } else {
      delete host.dataset.runtimeCellId;
    }
  });
};

export const markValuePending = (selector: string, projectionRevision: string) => {
  if (projectionRevision !== cacheProjectionRevision || !selectorHasOwner(selector)) {
    return;
  }
  const state = states.pending(selector, cachedValues.has(selector));
  hosts.forEach((host) => {
    if (selectorFor(host) === selector) {
      setState(host, state.phase);
    }
  });
};

export const markValueError = (
  selector: string,
  error: ValueReadError,
  projectionRevision: string,
) => {
  if (projectionRevision !== cacheProjectionRevision || !selectorHasOwner(selector)) {
    return;
  }
  cachedValues.delete(selector);
  states.clear(selector);
  states.failed(selector, error);
  hosts.forEach((host) => {
    if (selectorFor(host) === selector) {
      renderedValues.delete(host);
      const config = getRuntimeConfig();
      host.textContent = config.dev || config.mode === "edit" ? "Unavailable" : "";
      host.dataset.marimoStudioValueFallback = "";
      failHost(host, error);
    }
  });
};

export const applyValues = (values: Record<string, JsonValue>, projectionRevision: string) => {
  if (projectionRevision !== cacheProjectionRevision) {
    return;
  }
  for (const [selector, value] of Object.entries(values)) {
    if (!selectorHasOwner(selector)) {
      continue;
    }
    if (
      !cachedValues.has(selector) &&
      cachedValues.size >= getRuntimeConfig().projectionPolicy.maxUniqueValueTargets
    ) {
      markValueError(
        selector,
        {
          code: "projection-value-target-limit",
          message: "The active value cache reached its configured target limit.",
        },
        projectionRevision,
      );
      continue;
    }
    const projection = projectValue(value);
    cachedValues.set(selector, projection);
    states.resolved(selector);
    hosts.forEach((host) => {
      if (selectorFor(host) === selector) {
        renderHost(host, selector, projection);
      }
    });
  }
};
