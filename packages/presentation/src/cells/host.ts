import { isArtifactProjectionHost } from "../projections/artifact-host.ts";
import { notifyProjectionChanged } from "../projections/changes.ts";
import { hostsInDocumentOrder } from "../projections/host-order.ts";
import { PROJECTION_SITE_ATTRIBUTE } from "../projections/identity.ts";
import { resetProjectionHostMetadata } from "../projections/instances.ts";

export type CellHostState = "connecting" | "loading" | "stale" | "ready" | "missing" | "error";

type HostListener = () => void;

export interface CellHostEventDetail {
  readonly alias?: string;
  readonly runtimeId?: string;
  readonly outputMime?: string;
  readonly code?: string;
  readonly message?: string;
  readonly hint?: string;
}

const OUTPUT_SELECTOR = "[data-marimo-cell-output]";
const MEASURED_HEIGHT_PROPERTY = "--_marimo-cell-measured-height";
const PRESERVED_ID_PREFIX = "marimo-studio-cell-";
const RUNTIME_ATTRIBUTES = new Set([
  "aria-busy",
  "data-hx-preserve",
  "data-marimo-diagnostic-code",
  "data-marimo-diagnostic-hint",
  "data-marimo-diagnostic-message",
  "data-marimo-producer-ref",
  "data-marimo-projection-kind",
  "data-marimo-projection-target",
  "data-marimo-projection-variable",
  "data-marimo-studio-instance",
  "data-marimo-selector",
  "data-marimo-variable",
  "data-output-mime",
  "data-output-mimes",
  "data-runtime-cell-id",
  "data-state",
]);
const hosts = new Set<MarimoCellElement>();
const listeners = new Set<HostListener>();
const measuredHeights = new Map<string, number>();
let snapshot: readonly MarimoCellElement[] = [];
let activeViewportClass = "";
let resizeListenerRegistered = false;
let publishMovePending = false;

const viewportClass = (): string => {
  if (globalThis.innerWidth < 640) {
    return "compact";
  }
  if (globalThis.innerWidth < 1200) {
    return "regular";
  }
  return "wide";
};

const heightKey = (host: HTMLElement, view = viewportClass()): string => {
  return `${location.pathname}:${host.getAttribute("name")?.trim() ?? ""}:${view}`;
};

const readMeasuredHeight = (key: string): number | undefined => {
  const cached = measuredHeights.get(key);
  if (cached !== undefined) {
    return cached;
  }
  try {
    const stored = sessionStorage.getItem(`marimo-studio:height:${key}`);
    if (stored === null) {
      return undefined;
    }
    const height = Number(stored);
    if (!Number.isFinite(height) || height <= 0) {
      return undefined;
    }
    measuredHeights.set(key, height);
    return height;
  } catch {
    return undefined;
  }
};

const writeMeasuredHeight = (key: string, height: number) => {
  measuredHeights.set(key, height);
  try {
    sessionStorage.setItem(`marimo-studio:height:${key}`, String(height));
  } catch {
    // Browser storage is optional. The in-memory value still protects HTMX
    // remounts for the current document.
  }
};

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

const releaseCellHost = (host: MarimoCellElement) => {
  sizeObserver?.unobserve(host);
  if (!hosts.delete(host)) {
    return;
  }
  resetProjectionHostMetadata(host);
  delete host.dataset.state;
  host.removeAttribute("aria-busy");
  host.style.removeProperty(MEASURED_HEIGHT_PROPERTY);
  hosts.forEach(prepareCellHost);
  publish();
  notifyProjectionChanged();
};

const applyMeasuredHeight = (host: HTMLElement) => {
  const height = readMeasuredHeight(heightKey(host));
  if (height === undefined) {
    host.style.removeProperty(MEASURED_HEIGHT_PROPERTY);
    return;
  }
  host.style.setProperty(MEASURED_HEIGHT_PROPERTY, `${height}px`);
};

const rememberMeasuredHeight = (host: HTMLElement) => {
  if (host.dataset.state !== "ready" || !host.getAttribute("name")?.trim()) {
    return;
  }
  const height = Math.ceil(host.getBoundingClientRect().height);
  if (height <= 0 || measuredHeights.get(heightKey(host)) === height) {
    return;
  }
  writeMeasuredHeight(heightKey(host), height);
  applyMeasuredHeight(host);
};

const sizeObserver =
  "ResizeObserver" in globalThis
    ? new ResizeObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.target instanceof HTMLElement) {
            rememberMeasuredHeight(entry.target);
          }
        });
      })
    : null;

export class MarimoCellElement extends HTMLElement {
  static observedAttributes = ["name", PROJECTION_SITE_ATTRIBUTE];
  private hasRendered = false;

  get cellName(): string {
    return this.getAttribute("name")?.trim() ?? "";
  }

  connectedCallback() {
    if (!isArtifactProjectionHost(this)) {
      return;
    }
    prepareCellHost(this);
    hosts.add(this);
    applyMeasuredHeight(this);
    sizeObserver?.observe(this);
    if (!this.querySelector(OUTPUT_SELECTOR)) {
      setCellHostState(this, "connecting");
    }
    publish();
  }

  connectedMoveCallback() {
    if (!isArtifactProjectionHost(this)) {
      releaseCellHost(this);
      return;
    }
    if (!hosts.has(this)) {
      prepareCellHost(this);
      hosts.add(this);
      applyMeasuredHeight(this);
      sizeObserver?.observe(this);
      if (!this.querySelector(OUTPUT_SELECTOR)) {
        setCellHostState(this, "connecting");
      }
    }
    publishAfterMove();
    notifyProjectionChanged();
  }

  disconnectedCallback() {
    sizeObserver?.unobserve(this);
    queueMicrotask(() => {
      if (this.isConnected && isArtifactProjectionHost(this)) {
        return;
      }
      releaseCellHost(this);
    });
  }

  attributeChangedCallback(_name: string, previous: string | null, current: string | null) {
    if (!this.isConnected || previous === current || !isArtifactProjectionHost(this)) {
      return;
    }
    resetProjectionHostMetadata(this);
    setCellHostState(this, "connecting");
    applyMeasuredHeight(this);
    publish();
  }

  markRendered(): boolean {
    const updated = this.hasRendered;
    this.hasRendered = true;
    return updated;
  }
}

export const prepareCellHost = (host: Element) => {
  if (!isArtifactProjectionHost(host)) {
    return;
  }
  const name = host.getAttribute("name")?.trim();
  if (!name) {
    return;
  }
  if (host.hasAttribute("aria-label") && !host.hasAttribute("role")) {
    host.setAttribute("role", "group");
  }
  if (!host.id) {
    const id = `${PRESERVED_ID_PREFIX}${name}`;
    const existing = host.ownerDocument.getElementById(id);
    if (existing === null || existing === host) {
      host.id = id;
    }
  }
  if (host.id) {
    host.setAttribute("data-hx-preserve", "");
  }
};

export const prepareCellHosts = (root: ParentNode) => {
  root
    .querySelectorAll("marimo-cell")
    .forEach((host) => isArtifactProjectionHost(host) && prepareCellHost(host));
};

export const syncProjectionHostAttributes = (live: HTMLElement, source: Element): void => {
  const measuredHeight = live.style.getPropertyValue(MEASURED_HEIGHT_PROPERTY);
  for (const attribute of Array.from(live.attributes)) {
    if (!RUNTIME_ATTRIBUTES.has(attribute.name) && !source.hasAttribute(attribute.name)) {
      live.removeAttribute(attribute.name);
    }
  }
  for (const attribute of Array.from(source.attributes)) {
    if (
      !RUNTIME_ATTRIBUTES.has(attribute.name) &&
      live.getAttribute(attribute.name) !== attribute.value
    ) {
      live.setAttribute(attribute.name, attribute.value);
    }
  }
  live.style.removeProperty(MEASURED_HEIGHT_PROPERTY);
  if (measuredHeight) {
    live.style.setProperty(MEASURED_HEIGHT_PROPERTY, measuredHeight);
  }
};

export const syncPreservedCellHosts = (source: ParentNode, live: Document): void => {
  source.querySelectorAll<HTMLElement>("marimo-cell[data-hx-preserve][id]").forEach((host) => {
    if (!isArtifactProjectionHost(host)) {
      return;
    }
    const preserved = live.getElementById(host.id);
    if (preserved?.localName === "marimo-cell" && preserved !== host) {
      syncProjectionHostAttributes(preserved, host);
      prepareCellHost(preserved);
    }
  });
};

export const registerMarimoCellElement = () => {
  const existing = customElements.get("marimo-cell");
  if (existing && existing !== MarimoCellElement) {
    throw new Error("The marimo-cell custom element is already registered");
  }
  if (!existing) {
    customElements.define("marimo-cell", MarimoCellElement);
  }
  prepareCellHosts(document);
  if (!resizeListenerRegistered) {
    resizeListenerRegistered = true;
    activeViewportClass = viewportClass();
    globalThis.addEventListener("resize", () => {
      const next = viewportClass();
      if (next === activeViewportClass) {
        return;
      }
      activeViewportClass = next;
      hosts.forEach(applyMeasuredHeight);
    });
  }
};

export const getCellHosts = (): readonly MarimoCellElement[] => snapshot;

export const subscribeCellHosts = (listener: HostListener) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

export const setCellHostState = (
  host: MarimoCellElement,
  state: CellHostState,
  detail: CellHostEventDetail = {},
) => {
  const previous = host.dataset.state;
  host.dataset.state = state;
  if (state === "connecting" || state === "loading") {
    host.setAttribute("aria-busy", "true");
  } else {
    host.removeAttribute("aria-busy");
  }

  if (state === "ready" && previous !== "ready") {
    requestAnimationFrame(() => rememberMeasuredHeight(host));
    const name = host.markRendered() ? "marimo-cell-updated" : "marimo-cell-ready";
    host.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true, detail }));
  }
  if (state === "error" && previous !== "error") {
    host.dispatchEvent(
      new CustomEvent("marimo-cell-error", {
        bubbles: true,
        composed: true,
        detail,
      }),
    );
  }
  notifyProjectionChanged();
};
