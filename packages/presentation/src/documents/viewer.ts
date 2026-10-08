import type { DocumentRenderRequest, RenderedMedia } from "@marimo-studio/protocol/document-render";
import type { JsonValue } from "@marimo-studio/protocol/runtime-config";

import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { appendUrlPath } from "@marimo-studio/protocol/url";
import {
  projectDiagnosticSchema,
  type ProjectDiagnostic,
} from "@marimo-studio/protocol/view-project";
import { z } from "zod";

import type { MarimoCellElement } from "../cells/host.ts";
import type { MarimoOutputElement } from "../outputs/host.ts";

import { errorMessage } from "../errors.ts";
import { responseJsonOrNull } from "../json.ts";
import { notifyProjectionChanged } from "../projections/changes.ts";
import {
  projectionRequestForHost,
  projectionTargetForHost,
  projectionWireRequest,
} from "../projections/identity.ts";
import {
  getRuntimeConfig,
  hasRuntimeConfig,
  subscribeRuntimeConfig,
} from "../runtime-config/index.ts";
import { getValueHostProjections, isMarimoValueHost, valueHostCodec } from "../values/hosts.ts";
import { openPdf, type DocumentPages } from "./pdf.ts";

const RENDER_DELAY_MS = 150;
const RETRY_LIMIT = 3;
const PAGE_WIDTH = 920;
const PAGE_GUTTER = 16;
const HOST_EVENTS = ["value", "output", "cell"].flatMap((kind) =>
  ["ready", "updated", "error"].map((change) => `marimo-${kind}-${change}`),
);
// A stale host still holds its last value or output, and a change fires an event.
const SETTLED_STATES = new Set(["ready", "stale", "error"]);
const UNRENDERED_NOTE = "Showing the document without current notebook values.";
const diagnosticsSchema = z.array(projectDiagnosticSchema);
const elements = new Set<MarimoDocumentElement>();

const STYLE = `
:host { display: block; min-height: 100vh; background: color-mix(in srgb, CanvasText 7%, Canvas); }
.toolbar { position: sticky; top: 0; z-index: 2; display: flex; gap: 12px; align-items: center;
  justify-content: flex-end; padding: 8px 16px; font: 12px/1.4 system-ui, sans-serif;
  color: color-mix(in srgb, CanvasText 68%, transparent); background: inherit; }
.toolbar a { color: inherit; }
.toolbar a[hidden] { display: none; }
.problems { max-width: ${PAGE_WIDTH}px; margin: 0 auto; padding: 0 ${PAGE_GUTTER}px;
  font: 13px/1.5 system-ui, sans-serif; }
.problems article { margin-bottom: 8px; padding: 8px 12px; border-left: 3px solid #b45309;
  background: Canvas; color: CanvasText; }
.problems p { margin: 0; }
.problems .hint, .problems .source { color: color-mix(in srgb, CanvasText 66%, transparent); }
.pages { display: grid; gap: 16px; max-width: ${PAGE_WIDTH}px; margin: 0 auto;
  padding: 4px ${PAGE_GUTTER}px 32px; }
.page, .image { position: relative; width: 100%; background: white;
  box-shadow: 0 1px 3px rgb(0 0 0 / 0.16), 0 0 0 1px rgb(0 0 0 / 0.05); }
.page canvas, .image { display: block; width: 100%; height: 100%; }
.textLayer { position: absolute; inset: 0; overflow: clip; line-height: 1; text-align: initial;
  transform-origin: 0 0; --min-font-size: 1; --scale-round-x: 1px; --scale-round-y: 1px;
  --text-scale-factor: calc(var(--total-scale-factor) * var(--min-font-size));
  --min-font-size-inv: calc(1 / var(--min-font-size)); }
.textLayer :is(span, br) { color: transparent; position: absolute; white-space: pre; cursor: text;
  transform-origin: 0% 0%; }
.textLayer > :not(.markedContent), .textLayer .markedContent span:not(.markedContent) {
  --font-height: 0; font-size: calc(var(--text-scale-factor) * var(--font-height));
  --scale-x: 1; --rotate: 0deg;
  transform: rotate(var(--rotate)) scaleX(var(--scale-x)) scale(var(--min-font-size-inv)); }
.textLayer .markedContent { display: contents; }
`;

const problem = (code: string, message: string, hint = ""): ProjectDiagnostic => ({
  code,
  severity: "error",
  message,
  hint,
  source: null,
});

const canonicalJson = (value: JsonValue): string =>
  JSON.stringify(value, (_key, item: JsonValue) =>
    item === null || Array.isArray(item) || Object(item) !== item
      ? item
      : Object.fromEntries(Object.entries(item).sort(([left], [right]) => (left < right ? -1 : 1))),
  );

/** Name the results the document shows with their defaults, and why. */
const unavailableNote = (hosts: readonly HTMLElement[]): string => {
  const unavailable = hosts
    .filter((host) => host.dataset.state === "error")
    .map((host) => {
      const reason = host.dataset.marimoDiagnosticMessage?.replace(/\.$/u, "");
      return reason
        ? `${projectionTargetForHost(host)} (${reason})`
        : projectionTargetForHost(host);
    });
  return unavailable.length > 0 ? `Showing the default for ${unavailable.join(", ")}.` : "";
};

const sleep = (milliseconds: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, milliseconds));

const sameBytes = (left: Uint8Array, right: Uint8Array | undefined): boolean =>
  right !== undefined &&
  left.length === right.length &&
  left.every((byte, index) => byte === right[index]);

const media = (output: RenderedMedia | undefined): RenderedMedia | undefined =>
  output ? { mimetype: output.mimetype, data: output.data } : undefined;

const loadImage = async (blob: Blob, name: string): Promise<DocumentPages> => {
  const url = URL.createObjectURL(blob);
  const image = document.createElement("img");
  image.className = "image";
  image.alt = name;
  image.src = url;
  try {
    await image.decode();
  } catch (error) {
    URL.revokeObjectURL(url);
    throw error;
  }
  return { pages: [image], resize: () => {}, destroy: () => URL.revokeObjectURL(url) };
};

/**
 * Show the document a Studio document view publishes, and render it again
 * when one of the `mo-value`, `marimo-output`, or `marimo-cell` hosts inside
 * the element shows something new.
 */
export class MarimoDocumentElement extends HTMLElement {
  private readonly view = this.attachShadow({ mode: "open" });
  private readonly status = document.createElement("span");
  private readonly download = document.createElement("a");
  private readonly problems = document.createElement("div");
  private readonly pages = document.createElement("div");
  private request?: AbortController;
  private shown?: DocumentPages;
  private shownBytes?: Uint8Array;
  private shownPath?: string;
  private queued = false;
  private loop?: Promise<void>;
  private revision?: string;
  private documentUrl?: string;
  private release: (() => void)[] = [];

  constructor() {
    super();
    const style = document.createElement("style");
    style.textContent = STYLE;
    const toolbar = document.createElement("div");
    toolbar.className = "toolbar";
    this.status.setAttribute("role", "status");
    this.download.textContent = "Download";
    this.download.hidden = true;
    toolbar.append(this.status, this.download);
    this.problems.className = "problems";
    this.problems.setAttribute("role", "alert");
    this.pages.className = "pages";
    this.view.append(style, toolbar, this.problems, this.pages);
  }

  connectedCallback(): void {
    elements.add(this);
    if (this.release.length === 0) {
      const changed = () => this.schedule();
      HOST_EVENTS.forEach((name) => this.addEventListener(name, changed));
      // The viewer fills its frame, so a resized pane resizes the window.
      const resized = () => this.shown?.resize(this.pageWidth());
      globalThis.addEventListener("resize", resized);
      const unsubscribe = subscribeRuntimeConfig(() => {
        if (getRuntimeConfig().revision !== this.revision) {
          this.schedule();
        }
      });
      this.release = [
        ...HOST_EVENTS.map((name) => () => this.removeEventListener(name, changed)),
        () => globalThis.removeEventListener("resize", resized),
        unsubscribe,
      ];
    }
    this.setState("loading");
    this.schedule();
  }

  disconnectedCallback(): void {
    queueMicrotask(() => {
      if (this.isConnected) {
        return;
      }
      elements.delete(this);
      this.release.forEach((release) => release());
      this.release = [];
      this.request?.abort();
      this.shown?.destroy();
      this.shown = undefined;
      this.shownBytes = undefined;
      this.shownPath = undefined;
      if (this.documentUrl) {
        URL.revokeObjectURL(this.documentUrl);
        this.documentUrl = undefined;
      }
      notifyProjectionChanged();
    });
  }

  private setState(state: "loading" | "ready" | "error"): void {
    if (this.dataset.state === state) {
      return;
    }
    this.dataset.state = state;
    this.toggleAttribute("aria-busy", state === "loading");
    notifyProjectionChanged();
  }

  private schedule(): void {
    this.queued = true;
    this.loop ??= this.drain().finally(() => {
      this.loop = undefined;
      if (this.queued && this.isConnected) {
        this.schedule();
      }
    });
  }

  // Keep one render in flight. Changes during a render queue one more pass,
  // so the document catches up with the latest values once they settle.
  private async drain(): Promise<void> {
    let retries = 0;
    while (this.queued && this.isConnected) {
      await sleep(RENDER_DELAY_MS * 2 ** retries);
      this.queued = false;
      let retry = false;
      try {
        retry = await this.refresh(retries < RETRY_LIMIT);
      } catch (error) {
        if (this.request?.signal.aborted !== true) {
          this.showProblems([problem("document-render-failed", errorMessage(error))]);
        }
      }
      retries = retry ? retries + 1 : 0;
      this.queued ||= retry;
    }
  }

  private begin(): AbortSignal {
    this.request?.abort();
    this.request = new AbortController();
    if (!this.isConnected) {
      this.request.abort();
    }
    return this.request.signal;
  }

  private valueHosts(): HTMLElement[] {
    return Array.from(this.querySelectorAll<HTMLElement>("[mo-value]"));
  }

  private outputHosts(): MarimoOutputElement[] {
    return Array.from(this.querySelectorAll<MarimoOutputElement>("marimo-output"));
  }

  private cellHosts(): MarimoCellElement[] {
    return Array.from(this.querySelectorAll<MarimoCellElement>("marimo-cell"));
  }

  private pageWidth(): number {
    return this.pages.clientWidth > 0 ? this.pages.clientWidth - 2 * PAGE_GUTTER : PAGE_WIDTH;
  }

  /** Show the current document. Returns true when a transient failure should retry. */
  private async refresh(retry: boolean): Promise<boolean> {
    if (!hasRuntimeConfig()) {
      return false;
    }
    const config = getRuntimeConfig();
    const valueHosts = this.valueHosts();
    const outputHosts = this.outputHosts();
    const cellHosts = this.cellHosts();
    const hosts = [...valueHosts, ...outputHosts, ...cellHosts];
    this.revision = config.revision;
    const renders = this.hasAttribute("render") && hosts.length > 0;
    // The Browser runtime renders documents only in edit mode, so elsewhere it
    // shows the published document without waiting for notebook values.
    if (!renders || (config.runtime.id === "wasm" && config.mode !== "edit")) {
      await this.showSource(this.begin());
      return false;
    }
    if (hosts.some((host) => !SETTLED_STATES.has(host.dataset.state ?? ""))) {
      this.setState("loading");
      return false;
    }
    const signal = this.begin();
    if (config.runtime.id !== "server" && config.mode !== "edit") {
      await this.showSource(signal, this.preparedRendition());
      return false;
    }
    const body = this.renderBody(valueHosts, outputHosts, cellHosts);
    if ("code" in body) {
      await this.fail([body], signal);
      return false;
    }
    const headers = new Headers({ "Content-Type": "application/json" });
    if (config.presentationSessionId) {
      headers.set("Marimo-Session-Id", config.presentationSessionId);
    }
    this.setState("loading");
    this.status.textContent = "Rendering…";
    let response: Response;
    try {
      response = await fetch(appendUrlPath(config.supportUrl, "render"), {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal,
      });
    } catch (error) {
      // A dropped connection is transient, so the render retries.
      if (signal.aborted) {
        return false;
      }
      if (retry) {
        return true;
      }
      throw error;
    }
    if (response.ok) {
      await this.show(await response.blob(), signal, unavailableNote(hosts));
      this.shownPath = undefined;
      return false;
    }
    const detail = parseErrorResponse(await responseJsonOrNull(response));
    if (signal.aborted) {
      return false;
    }
    if (detail.transient && retry) {
      return true;
    }
    const diagnostics = diagnosticsSchema.safeParse(detail.diagnostics);
    await this.fail(
      diagnostics.success
        ? diagnostics.data
        : [
            problem(
              detail.error ?? "document-render-failed",
              detail.message ?? `Rendering failed with ${response.status}.`,
            ),
          ],
      signal,
    );
    return false;
  }

  private renderBody(
    valueHosts: readonly HTMLElement[],
    outputHosts: readonly MarimoOutputElement[],
    cellHosts: readonly MarimoCellElement[],
  ): DocumentRenderRequest | ProjectDiagnostic {
    const config = getRuntimeConfig();
    if (config.runtime.id === "server") {
      const projections = (hosts: readonly HTMLElement[], kind: "output" | "cell") =>
        hosts.map((host) =>
          projectionWireRequest(
            projectionRequestForHost(host, kind, projectionTargetForHost(host, kind)),
          ),
        );
      return {
        revision: config.revision,
        valueProjections: getValueHostProjections()
          .filter(({ host }) => valueHosts.includes(host))
          .map(({ request }) => projectionWireRequest(request)),
        outputProjections: projections(outputHosts, "output"),
        cellProjections: projections(cellHosts, "cell"),
      };
    }
    const values: Record<string, JsonValue> = {};
    for (const host of valueHosts) {
      if (host.dataset.state === "error" || !isMarimoValueHost(host)) {
        continue;
      }
      const selector = host.getAttribute("mo-value")?.trim() ?? "";
      if (valueHostCodec(host) === "arrow-ipc-v1") {
        return problem(
          "render-value-not-json",
          `${selector} is a table, and documents read JSON values.`,
          "Project tables as a list of dictionaries in the notebook, for example with df.to_dicts().",
        );
      }
      const value = host.marimoValue;
      if (value !== undefined) {
        // SAFETY: Only Arrow-coded hosts hold tables, and those returned above.
        values[selector] = value as JsonValue;
      }
    }
    const shown = (hosts: readonly (MarimoOutputElement | MarimoCellElement)[]) => {
      const results: Record<string, RenderedMedia> = {};
      for (const host of hosts) {
        const output = media(host.marimoOutput);
        if (host.dataset.state !== "error" && output) {
          results[projectionTargetForHost(host)] = output;
        }
      }
      return results;
    };
    return {
      revision: config.revision,
      values,
      outputs: shown(outputHosts),
      cells: shown(cellHosts),
    };
  }

  /** Return the published document's file suffix, such as `.pdf`. */
  private suffix(): string {
    return /\.[^./]+$/u.exec(this.getAttribute("src") ?? "")?.[0] ?? "";
  }

  /** Return the export's rendition for the prepared state the reader is viewing. */
  private preparedRendition(): string | undefined {
    const state = globalThis.marimoStudio.state;
    const suffix = this.suffix();
    if (!state || !suffix) {
      return undefined;
    }
    const inputs = canonicalJson(state.inputs());
    const current = state.states().find((item) => canonicalJson(item.inputs) === inputs);
    return current ? `renditions/${current.fingerprint}${suffix}` : undefined;
  }

  private downloadName(): string {
    return (this.getAttribute("src") ?? "document").split("/").pop() ?? "document";
  }

  /**
   * Show `rendition` when the server has it, else the published document. The
   * published document of a rendering view carries no notebook values, so the
   * toolbar says so.
   */
  private async showSource(signal: AbortSignal, rendition?: string): Promise<void> {
    if (this.shown && this.shownPath === (rendition ?? this.getAttribute("src"))) {
      return;
    }
    const fetchDocument = (path: string) => fetch(new URL(path, document.baseURI), { signal });
    let response = rendition === undefined ? undefined : await fetchDocument(rendition);
    const rendered = response?.ok === true;
    if (!response?.ok) {
      response = await fetchDocument(this.getAttribute("src") ?? "");
    }
    if (!response.ok) {
      throw new Error(`The document is unavailable (${response.status}).`);
    }
    const unrendered =
      this.hasAttribute("render") &&
      this.valueHosts().length + this.outputHosts().length + this.cellHosts().length > 0 &&
      !rendered;
    await this.show(await response.blob(), signal, unrendered ? UNRENDERED_NOTE : "");
    if (!signal.aborted) {
      this.shownPath = rendered ? rendition : (this.getAttribute("src") ?? undefined);
    }
  }

  /** Swap in a document and mark the viewer ready unless `signal` aborted. */
  private async show(blob: Blob, signal: AbortSignal, note: string): Promise<void> {
    await this.display(blob, signal);
    if (signal.aborted) {
      return;
    }
    this.status.textContent = note;
    this.problems.replaceChildren();
    this.setState("ready");
  }

  private async display(blob: Blob, signal: AbortSignal): Promise<void> {
    const name = this.downloadName();
    const bytes = new Uint8Array(await blob.arrayBuffer());
    // Hosts settle again after every upstream run, which often renders the
    // same document. Keep the painted pages when the bytes did not change.
    if (this.shown && sameBytes(bytes, this.shownBytes)) {
      return;
    }
    const shown =
      (this.getAttribute("type") ?? blob.type) === "application/pdf"
        ? await openPdf(bytes, this.pageWidth(), signal)
        : await loadImage(blob, name);
    if (signal.aborted) {
      shown.destroy();
      return;
    }
    this.shown?.destroy();
    this.shown = shown;
    this.shownBytes = bytes;
    this.pages.replaceChildren(...shown.pages);
    if (this.documentUrl) {
      URL.revokeObjectURL(this.documentUrl);
    }
    this.documentUrl = URL.createObjectURL(blob);
    this.download.href = this.documentUrl;
    this.download.download = name;
    this.download.hidden = false;
  }

  /** Report `diagnostics`, keeping the last document, or the published one when none shows. */
  private async fail(
    diagnostics: readonly ProjectDiagnostic[],
    signal: AbortSignal,
  ): Promise<void> {
    this.showProblems(diagnostics);
    if (this.shown) {
      return;
    }
    const response = await fetch(new URL(this.getAttribute("src") ?? "", document.baseURI), {
      signal,
    }).catch(() => undefined);
    if (response?.ok) {
      await this.display(await response.blob(), signal);
    }
  }

  private showProblems(diagnostics: readonly ProjectDiagnostic[]): void {
    this.problems.replaceChildren(
      ...diagnostics.map((diagnostic) => {
        const article = document.createElement("article");
        const message = document.createElement("p");
        message.textContent = diagnostic.message;
        article.append(message);
        if (diagnostic.source) {
          const source = document.createElement("p");
          source.className = "source";
          source.textContent = `${diagnostic.source.path}:${diagnostic.source.line}`;
          article.append(source);
        }
        if (diagnostic.hint) {
          const hint = document.createElement("p");
          hint.className = "hint";
          hint.textContent = diagnostic.hint;
          article.append(hint);
        }
        return article;
      }),
    );
    this.status.textContent = "";
    this.setState("error");
  }
}

export const getDocumentHosts = (): readonly HTMLElement[] => Array.from(elements);

export const registerMarimoDocumentElement = (): void => {
  const existing = customElements.get("marimo-document");
  if (existing && existing !== MarimoDocumentElement) {
    throw new Error("The marimo-document custom element is already registered");
  }
  if (!existing) {
    customElements.define("marimo-document", MarimoDocumentElement);
  }
};
