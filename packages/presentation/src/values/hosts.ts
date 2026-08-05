import type { ValueReadError } from "@marimo-studio/protocol/value-read";

import { notifyReadinessChanged } from "../readiness.ts";
import {
  getRuntimeConfig,
  type JsonValue,
  type ProjectionDiagnostic,
  subscribeRuntimeConfig,
  type ValueBindingConfig,
} from "../runtime-config/index.ts";
import { type ValuePhase, ValueStates } from "./state.ts";

const ATTRIBUTE = "mo-value";
const ATTRIBUTE_SELECTOR = `[${ATTRIBUTE}]`;
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
const states = new ValueStates();
let bindings: Record<string, ValueBindingConfig> = {};
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

const prepareHost = (host: HTMLElement): MarimoValueHost => {
  if (!preparedHosts.has(host)) {
    Object.defineProperty(host, "marimoValue", {
      configurable: true,
      enumerable: false,
      get: () => hostValues.get(host),
    });
    preparedHosts.add(host);
  }
  return host as MarimoValueHost;
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

const bindingFor = (host: HTMLElement): ValueBindingConfig | undefined => {
  return bindings[selectorFor(host)];
};

const diagnosticFor = (selector: string): ProjectionDiagnostic | undefined => {
  return getRuntimeConfig().diagnostics.find(
    (diagnostic) => diagnostic.projection === "value" && diagnostic.target === selector,
  );
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

const setState = (host: HTMLElement, state: ValuePhase): boolean => {
  const previous = host.dataset.state;
  host.dataset.state = state;
  if (["connecting", "loading", "stale"].includes(state)) {
    host.setAttribute("aria-busy", "true");
  } else {
    host.removeAttribute("aria-busy");
  }
  notifyReadinessChanged();
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
  const detail: MarimoValueErrorDetail = {
    selector: selectorFor(host),
    code: error.code,
    message: error.message,
    ...(hint ? { hint } : {}),
  };
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

const clearProjectedValue = (host: HTMLElement, selector: string) => {
  cachedValues.delete(selector);
  states.clear(selector);
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
  if (typeof value === "string") {
    return { fingerprint, text: value, value };
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return { fingerprint, text: String(value), value };
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

const connectHost = (host: HTMLElement) => {
  prepareHost(host);
  hosts.add(host);
  const selector = selectorFor(host);
  hostSelectors.set(host, selector);
  const binding = bindingFor(host);
  if (!binding) {
    delete host.dataset.marimoSelector;
    delete host.dataset.marimoVariable;
    const diagnostic = diagnosticFor(selector);
    clearProjectedValue(host, selector);
    failHost(
      host,
      {
        code: diagnostic?.code ?? "unknown-selector",
        message: diagnostic?.message ?? `Unknown selector ${JSON.stringify(selector)}`,
      },
      diagnostic,
    );
    return;
  }
  clearHostDiagnostic(host);
  host.dataset.marimoSelector = selector;
  host.dataset.marimoVariable = binding.variable;
  const cached = cachedValues.has(selector);
  const state = states.connected(selector, cached);
  if (state.phase === "error" && state.error) {
    failHost(host, state.error);
  } else if (cached) {
    renderHost(host, selector, cachedValues.get(selector) as ProjectedValue, state.phase);
  } else {
    clearHostValue(host);
    setState(host, state.phase);
  }
};

const disconnectHost = (host: HTMLElement) => {
  hosts.delete(host);
};

const releaseHost = (host: HTMLElement) => {
  disconnectHost(host);
  if (renderedValues.delete(host)) {
    host.textContent = "";
  }
  hostValues.delete(host);
  hostSelectors.delete(host);
  if (preparedHosts.delete(host)) {
    Reflect.deleteProperty(host, "marimoValue");
  }
  clearHostDiagnostic(host);
  delete host.dataset.marimoSelector;
  delete host.dataset.marimoVariable;
  delete host.dataset.state;
  host.removeAttribute("aria-busy");
  notifyReadinessChanged();
};

const reconcileHosts = () => {
  if (!started) {
    return;
  }
  hosts.forEach((host) => {
    if (!host.isConnected || !host.matches(ATTRIBUTE_SELECTOR)) {
      disconnectHost(host);
    }
  });
  visit(document.documentElement, connectHost);
};

const configure = () => {
  bindings = getRuntimeConfig().valueBindings;
  if (configurePending) {
    return;
  }
  configurePending = true;
  queueMicrotask(() => {
    configurePending = false;
    reconcileHosts();
  });
};

export const startValueBindings = () => {
  started = true;
  bindings = getRuntimeConfig().valueBindings;
  reconcileHosts();
  observer?.disconnect();
  observer = new MutationObserver((records) => {
    const changedHosts = new Set<HTMLElement>();
    for (const record of records) {
      if (record.type === "attributes") {
        if (record.target instanceof HTMLElement) {
          changedHosts.add(record.target);
        }
        continue;
      }
      record.removedNodes.forEach((node) => visit(node, disconnectHost));
      record.addedNodes.forEach((node) => visit(node, connectHost));
    }
    changedHosts.forEach((host) => {
      if (!host.isConnected) {
        disconnectHost(host);
        return;
      }
      const attribute = host.getAttribute(ATTRIBUTE);
      const nextSelector = attribute === null ? null : attribute.trim();
      if (nextSelector === hostSelectors.get(host)) {
        return;
      }
      releaseHost(host);
      if (nextSelector !== null) {
        connectHost(host);
      }
    });
  });
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: [ATTRIBUTE],
    childList: true,
    subtree: true,
  });
  unsubscribeConfig?.();
  unsubscribeConfig = subscribeRuntimeConfig(configure);
};

export const stopValueBindings = () => {
  started = false;
  observer?.disconnect();
  observer = undefined;
  unsubscribeConfig?.();
  unsubscribeConfig = undefined;
  hosts.clear();
};

export const markValuePending = (selector: string) => {
  const state = states.pending(selector, cachedValues.has(selector));
  hosts.forEach((host) => {
    if (selectorFor(host) === selector) {
      setState(host, state.phase);
    }
  });
};

export const markValueError = (selector: string, error: ValueReadError) => {
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

export const applyValues = (values: Record<string, JsonValue>) => {
  for (const [selector, value] of Object.entries(values)) {
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
