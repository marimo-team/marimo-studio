import {
  getRuntimeConfig,
  type JsonValue,
  subscribeRuntimeConfig,
  type ValueBindingConfig,
} from "./runtime-config.ts";
import { notifyReadinessChanged } from "./readiness.ts";
import {
  type ValuePhase,
  type ValueReadError,
  ValueStates,
} from "./value-state.ts";

export interface ValueReadResponse {
  values: Record<string, JsonValue>;
  errors: Record<string, ValueReadError>;
}

export class ValueRequestError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly transient: boolean,
  ) {
    super(message);
    this.name = "ValueRequestError";
  }
}

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

const setState = (
  host: HTMLElement,
  state: ValuePhase,
  detail: Record<string, unknown> = {},
) => {
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

const failHost = (host: HTMLElement, error: ValueReadError) => {
  host.dataset.marimoError = error.message;
  host.dataset.marimoErrorCode = error.code;
  setState(host, "error", {
    selector: selectorFor(host),
    code: error.code,
    message: error.message,
  });
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
  const fingerprint = JSON.stringify(value);
  const changed = renderedValues.get(host) !== fingerprint;
  if (changed) {
    host.textContent = textFor(value);
    renderedValues.set(host, fingerprint);
  }
  delete host.dataset.marimoError;
  delete host.dataset.marimoErrorCode;
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
    failHost(host, {
      code: "unknown-selector",
      message: `Unknown selector ${JSON.stringify(selector)}`,
    });
    return;
  }
  host.dataset.marimoSelector = selector;
  host.dataset.marimoVariable = binding.variable;
  const cached = cachedValues.has(selector);
  const state = states.connected(selector, cached);
  if (state.phase === "error" && state.error) {
    failHost(host, state.error);
  } else if (cached) {
    renderHost(
      host,
      selector,
      cachedValues.get(selector) as JsonValue,
      state.phase,
    );
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

export const markValueError = (
  selector: string,
  error: ValueReadError,
) => {
  states.failed(selector, error);
  hosts.forEach((host) => {
    if (selectorFor(host) === selector) {
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

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return typeof value === "object" && value !== null && !Array.isArray(value);
};

export const readValues = async (
  sessionId: string,
  selectors: string[],
  signal?: AbortSignal,
): Promise<ValueReadResponse> => {
  const config = getRuntimeConfig();
  const response = await fetch(`${config.supportUrl}/values`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Marimo-Server-Token": config.serverToken,
      "Marimo-Session-Id": sessionId,
    },
    body: JSON.stringify({ selectors }),
    signal,
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => undefined);
    const message = isRecord(payload) && typeof payload.message === "string"
      ? payload.message
      : `Value request failed with ${response.status}`;
    const code = isRecord(payload) && typeof payload.error === "string"
      ? payload.error
      : "value-request-failed";
    const transient =
      isRecord(payload) && typeof payload.transient === "boolean"
        ? payload.transient
        : false;
    throw new ValueRequestError(message, code, transient);
  }
  const payload: unknown = await response.json();
  if (
    !isRecord(payload) ||
    !isRecord(payload.values) ||
    !isRecord(payload.errors) ||
    !Object.values(payload.errors).every((error) =>
      isRecord(error) &&
      typeof error.code === "string" &&
      typeof error.message === "string"
    )
  ) {
    throw new Error("Value response has an invalid shape");
  }
  return payload as unknown as ValueReadResponse;
};

const retryDelays = [250, 500, 1_000, 2_000];

const waitForRetry = (delay: number, signal?: AbortSignal): Promise<void> => {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("The request was aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      clearTimeout(timeout);
      reject(new DOMException("The request was aborted", "AbortError"));
    };
    const timeout = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, delay);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
};

export const readValuesWithRetry = async (
  sessionId: string,
  selectors: string[],
  signal?: AbortSignal,
): Promise<ValueReadResponse> => {
  for (let attempt = 0;; attempt += 1) {
    try {
      return await readValues(sessionId, selectors, signal);
    } catch (error) {
      if (
        !(error instanceof ValueRequestError) ||
        !error.transient ||
        attempt >= retryDelays.length
      ) {
        throw error;
      }
      await waitForRetry(retryDelays[attempt], signal);
    }
  }
};
