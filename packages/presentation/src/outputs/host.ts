import { syncProjectionHostAttributes } from "../cells/host.ts";
import { isArtifactProjectionHost } from "../projections/artifact-host.ts";
import { notifyProjectionChanged } from "../projections/changes.ts";
import { hostsInDocumentOrder } from "../projections/host-order.ts";
import {
  PROJECTION_PRESERVE_ATTRIBUTE,
  PROJECTION_SITE_ATTRIBUTE,
} from "../projections/identity.ts";
import { resetProjectionHostMetadata } from "../projections/instances.ts";

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
let publishMovePending = false;

const publish = () => {
  snapshot = hostsInDocumentOrder(hosts);
  listeners.forEach((listener) => listener());
};

const publishAfterMove = () => {
  if (publishMovePending) {
    return;
  }
  publishMovePending = true;
  queueMicrotask(() => {
    publishMovePending = false;
    const next = hostsInDocumentOrder(hosts);
    if (next.length !== snapshot.length || next.some((host, index) => host !== snapshot[index])) {
      publish();
    }
  });
};

const releaseOutputHost = (host: MarimoOutputElement) => {
  if (!hosts.delete(host)) {
    return;
  }
  resetProjectionHostMetadata(host);
  delete host.dataset.state;
  host.removeAttribute("aria-busy");
  hosts.forEach(prepareOutputHost);
  publish();
  notifyProjectionChanged();
};

export class MarimoOutputElement extends HTMLElement {
  static observedAttributes = ["value", PROJECTION_SITE_ATTRIBUTE];
  private hasRendered = false;

  get valueSelector(): string {
    return this.getAttribute("value")?.trim() ?? "";
  }

  connectedCallback() {
    if (!isArtifactProjectionHost(this)) {
      return;
    }
    prepareOutputHost(this);
    hosts.add(this);
    if (!this.querySelector(OUTPUT_SELECTOR)) {
      setOutputHostState(this, "connecting");
    }
    publish();
  }

  connectedMoveCallback() {
    if (!isArtifactProjectionHost(this)) {
      releaseOutputHost(this);
      return;
    }
    if (!hosts.has(this)) {
      prepareOutputHost(this);
      hosts.add(this);
      if (!this.querySelector(OUTPUT_SELECTOR)) {
        setOutputHostState(this, "connecting");
      }
    }
    publishAfterMove();
    notifyProjectionChanged();
  }

  disconnectedCallback() {
    queueMicrotask(() => {
      if (this.isConnected && isArtifactProjectionHost(this)) {
        return;
      }
      releaseOutputHost(this);
    });
  }

  attributeChangedCallback(_name: string, previous: string | null, current: string | null) {
    if (!this.isConnected || previous === current || !isArtifactProjectionHost(this)) {
      return;
    }
    resetProjectionHostMetadata(this);
    setOutputHostState(this, "connecting");
    prepareOutputHost(this);
    publish();
  }

  markRendered(): boolean {
    const updated = this.hasRendered;
    this.hasRendered = true;
    return updated;
  }
}

export const prepareOutputHost = (host: Element) => {
  if (!isArtifactProjectionHost(host)) {
    return;
  }
  const selector = host.getAttribute("value")?.trim();
  if (!selector) {
    return;
  }
  if (host.hasAttribute("aria-label") && !host.hasAttribute("role")) {
    host.setAttribute("role", "group");
  }
  if (!host.id) {
    const id = `${PRESERVED_ID_PREFIX}${encodeURIComponent(selector)}`;
    const existing = host.ownerDocument.getElementById(id);
    if (existing === null || existing === host) {
      host.id = id;
    }
  }
  if (host.id) {
    host.setAttribute(PROJECTION_PRESERVE_ATTRIBUTE, "");
  }
};

export const prepareOutputHosts = (root: ParentNode) => {
  root
    .querySelectorAll("marimo-output")
    .forEach((host) => isArtifactProjectionHost(host) && prepareOutputHost(host));
};

export const syncPreservedOutputHosts = (source: ParentNode, live: Document): void => {
  source
    .querySelectorAll<HTMLElement>(`marimo-output[${PROJECTION_PRESERVE_ATTRIBUTE}][id]`)
    .forEach((host) => {
      if (!isArtifactProjectionHost(host)) {
        return;
      }
      const preserved = live.getElementById(host.id);
      if (
        preserved?.localName === "marimo-output" &&
        preserved !== host &&
        isArtifactProjectionHost(preserved)
      ) {
        syncProjectionHostAttributes(preserved, host);
        prepareOutputHost(preserved);
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
