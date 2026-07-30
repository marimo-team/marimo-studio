import { notifyReadinessChanged } from "./readiness.ts";

export type CellHostState =
  | "connecting"
  | "loading"
  | "stale"
  | "ready"
  | "missing"
  | "error";

type HostListener = () => void;

const OUTPUT_SELECTOR = "[data-marimo-cell-output]";
const MEASURED_HEIGHT_PROPERTY = "--_marimo-cell-measured-height";
const PRESERVED_ID_PREFIX = "marimo-studio-cell-";
const hosts = new Set<MarimoCellElement>();
const listeners = new Set<HostListener>();
const measuredHeights = new Map<string, number>();
let snapshot: readonly MarimoCellElement[] = [];
let activeViewportClass = "";
let resizeListenerRegistered = false;

const viewportClass = (): string => {
  if (globalThis.innerWidth < 640) {
    return "compact";
  }
  if (globalThis.innerWidth < 1200) {
    return "regular";
  }
  return "wide";
};

const heightKey = (
  host: MarimoCellElement,
  view = viewportClass(),
): string => {
  return `${location.pathname}:${host.cellName}:${view}`;
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
  snapshot = Array.from(hosts);
  listeners.forEach((listener) => listener());
};

const applyMeasuredHeight = (host: MarimoCellElement) => {
  const height = readMeasuredHeight(heightKey(host));
  if (height === undefined) {
    host.style.removeProperty(MEASURED_HEIGHT_PROPERTY);
    return;
  }
  host.style.setProperty(MEASURED_HEIGHT_PROPERTY, `${height}px`);
};

const rememberMeasuredHeight = (host: MarimoCellElement) => {
  if (host.dataset.state !== "ready" || !host.cellName) {
    return;
  }
  const height = Math.ceil(host.getBoundingClientRect().height);
  if (height <= 0 || measuredHeights.get(heightKey(host)) === height) {
    return;
  }
  writeMeasuredHeight(heightKey(host), height);
  applyMeasuredHeight(host);
};

const sizeObserver = typeof ResizeObserver === "undefined"
  ? null
  : new ResizeObserver((entries) => {
    entries.forEach((entry) => {
      rememberMeasuredHeight(entry.target as MarimoCellElement);
    });
  });

export class MarimoCellElement extends HTMLElement {
  static observedAttributes = ["name"];
  private hasRendered = false;

  get cellName(): string {
    return this.getAttribute("name")?.trim() ?? "";
  }

  connectedCallback() {
    prepareCellHost(this);
    hosts.add(this);
    applyMeasuredHeight(this);
    sizeObserver?.observe(this);
    if (!this.querySelector(OUTPUT_SELECTOR)) {
      setCellHostState(this, "connecting");
    }
    publish();
  }

  connectedMoveCallback() {}

  disconnectedCallback() {
    sizeObserver?.unobserve(this);
    queueMicrotask(() => {
      if (this.isConnected) {
        return;
      }
      hosts.delete(this);
      hosts.forEach(prepareCellHost);
      publish();
    });
  }

  attributeChangedCallback() {
    if (this.isConnected) {
      applyMeasuredHeight(this);
      publish();
    }
  }

  markRendered(): boolean {
    const updated = this.hasRendered;
    this.hasRendered = true;
    return updated;
  }
}

export const prepareCellHost = (host: Element) => {
  const name = host.getAttribute("name")?.trim();
  if (!name) {
    return;
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
  root.querySelectorAll("marimo-cell").forEach(prepareCellHost);
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
  detail: Record<string, unknown> = {},
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
    const name = host.markRendered()
      ? "marimo-cell-updated"
      : "marimo-cell-ready";
    host.dispatchEvent(
      new CustomEvent(name, { bubbles: true, composed: true, detail }),
    );
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
  notifyReadinessChanged();
};
