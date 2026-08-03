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
const renderedValues = new WeakMap<HTMLElement, string>();
const cachedValues = new Map<string, JsonValue>();
const states = new ValueStates();
let bindings: Record<string, ValueBindingConfig> = {};
let observer: MutationObserver | undefined;
let unsubscribeConfig: (() => void) | undefined;

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

const setState = (host: HTMLElement, state: ValuePhase, detail: Record<string, unknown> = {}) => {
  const previous = host.dataset.state;
  host.dataset.state = state;
  if (["connecting", "loading", "stale"].includes(state)) {
    host.setAttribute("aria-busy", "true");
  } else {
    host.removeAttribute("aria-busy");
  }
  if (state === "error" && previous !== "error") {
    host.dispatchEvent(
      new CustomEvent("marimo-value-error", {
        bubbles: true,
        composed: true,
        detail,
      }),
    );
  }
  notifyReadinessChanged();
};

const failHost = (host: HTMLElement, error: ValueReadError, diagnostic?: ProjectionDiagnostic) => {
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
  setState(host, "error", {
    selector: selectorFor(host),
    code: error.code,
    message: error.message,
    hint,
  });
};

const clearProjectedValue = (host: HTMLElement, selector: string) => {
  cachedValues.delete(selector);
  states.clear(selector);
  renderedValues.delete(host);
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

const textFor = (value: JsonValue): string => {
  if (value === null) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
};

const renderHost = (
  host: HTMLElement,
  selector: string,
  value: JsonValue,
  phase: ValuePhase = "ready",
) => {
  clearHostDiagnostic(host);
  const fingerprint = JSON.stringify(value);
  const changed = renderedValues.get(host) !== fingerprint;
  if (changed) {
    host.textContent = textFor(value);
    renderedValues.set(host, fingerprint);
  }
  setState(host, phase, { selector, value });
  if (changed && phase === "ready") {
    host.dispatchEvent(
      new CustomEvent("marimo-value-updated", {
        bubbles: true,
        composed: true,
        detail: { selector, value },
      }),
    );
  }
};

const connectHost = (host: HTMLElement) => {
  hosts.add(host);
  const selector = selectorFor(host);
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
    renderHost(host, selector, cachedValues.get(selector) as JsonValue, state.phase);
  } else {
    setState(host, state.phase, { selector });
  }
};

const disconnectHost = (host: HTMLElement) => {
  hosts.delete(host);
};

const configure = () => {
  bindings = getRuntimeConfig().valueBindings;
  Array.from(hosts).forEach(connectHost);
};

export const startValueBindings = () => {
  bindings = getRuntimeConfig().valueBindings;
  visit(document.documentElement, connectHost);
  observer?.disconnect();
  observer = new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === "attributes") {
        disconnectHost(record.target as HTMLElement);
        connectHost(record.target as HTMLElement);
        continue;
      }
      record.removedNodes.forEach((node) => visit(node, disconnectHost));
      record.addedNodes.forEach((node) => visit(node, connectHost));
    }
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

export const markValuePending = (selector: string) => {
  const state = states.pending(selector, cachedValues.has(selector));
  hosts.forEach((host) => {
    if (selectorFor(host) === selector) {
      setState(host, state.phase, { selector });
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
    cachedValues.set(selector, value);
    states.resolved(selector);
    hosts.forEach((host) => {
      if (selectorFor(host) === selector) {
        renderHost(host, selector, value);
      }
    });
  }
};
