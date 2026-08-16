import { syncProjectionHostAttributes } from "../cells/host.ts";
import { notifyProjectionChanged } from "../projections/changes.ts";

export type OutputHostState = "connecting" | "loading" | "stale" | "ready" | "error";

type HostListener = () => void;

export interface OutputHostEventDetail {
  readonly selector?: string;
  readonly cellId?: string;
  readonly mimetype?: string;
  readonly code?: string;
  readonly message?: string;
  readonly hint?: string;
}

const OUTPUT_SELECTOR = "[data-marimo-cell-output]";
const PRESERVED_ID_PREFIX = "marimo-studio-output-";
const hosts = new Set<MarimoOutputElement>();
const listeners = new Set<HostListener>();
let snapshot: readonly MarimoOutputElement[] = [];

const publish = () => {
  snapshot = Array.from(hosts);
  listeners.forEach((listener) => listener());
};

export class MarimoOutputElement extends HTMLElement {
  static observedAttributes = ["value"];
  private hasRendered = false;

  get valueSelector(): string {
    return this.getAttribute("value")?.trim() ?? "";
  }

  connectedCallback() {
    prepareOutputHost(this);
    hosts.add(this);
    if (!this.querySelector(OUTPUT_SELECTOR)) {
      setOutputHostState(this, "connecting");
    }
    publish();
  }

  connectedMoveCallback() {}

  disconnectedCallback() {
    queueMicrotask(() => {
      if (this.isConnected) {
        return;
      }
      hosts.delete(this);
      hosts.forEach(prepareOutputHost);
      publish();
    });
  }

  attributeChangedCallback() {
    if (this.isConnected) {
      prepareOutputHost(this);
      publish();
    }
  }

  markRendered(): boolean {
    const updated = this.hasRendered;
    this.hasRendered = true;
    return updated;
  }
}

export const prepareOutputHost = (host: Element) => {
  const selector = host.getAttribute("value")?.trim();
  if (!selector) {
    return;
  }
  if (!host.id) {
    const id = `${PRESERVED_ID_PREFIX}${encodeURIComponent(selector)}`;
    const existing = host.ownerDocument.getElementById(id);
    if (existing === null || existing === host) {
      host.id = id;
    }
  }
  if (host.id) {
    host.setAttribute("data-hx-preserve", "");
  }
};

export const prepareOutputHosts = (root: ParentNode) => {
  root.querySelectorAll("marimo-output").forEach(prepareOutputHost);
};

export const syncPreservedOutputHosts = (source: ParentNode, live: Document): void => {
  source.querySelectorAll<HTMLElement>("marimo-output[data-hx-preserve][id]").forEach((host) => {
    const preserved = live.getElementById(host.id);
    if (preserved?.localName === "marimo-output" && preserved !== host) {
      syncProjectionHostAttributes(preserved, host);
    }
  });
};

export const registerMarimoOutputElement = () => {
  const existing = customElements.get("marimo-output");
  if (existing && existing !== MarimoOutputElement) {
    throw new Error("The marimo-output custom element is already registered");
  }
  if (!existing) {
    customElements.define("marimo-output", MarimoOutputElement);
  }
  prepareOutputHosts(document);
};

export const getOutputHosts = (): readonly MarimoOutputElement[] => snapshot;

export const subscribeOutputHosts = (listener: HostListener) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export const setOutputHostState = (
  host: MarimoOutputElement,
  state: OutputHostState,
  detail: OutputHostEventDetail = {},
) => {
  const previous = host.dataset.state;
  host.dataset.state = state;
  if (state === "connecting" || state === "loading" || state === "stale") {
    host.setAttribute("aria-busy", "true");
  } else {
    host.removeAttribute("aria-busy");
  }
  if (state === "ready" && previous !== "ready") {
    const name = host.markRendered() ? "marimo-output-updated" : "marimo-output-ready";
    host.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true, detail }));
  }
  if (state === "error" && previous !== "error") {
    host.dispatchEvent(
      new CustomEvent("marimo-output-error", {
        bubbles: true,
        composed: true,
        detail,
      }),
    );
  }
  notifyProjectionChanged();
};
