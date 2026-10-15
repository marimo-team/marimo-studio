import type { ProjectDiagnostic } from "@marimo-studio/protocol/view-project";

import { openPdf } from "./pdf.ts";

/** One file of a render's bundle, with the URL the page fetches it from. */
export interface RenderFileRecord {
  readonly path: string;
  readonly mediaType: string;
  readonly size: number;
  readonly url: string;
}

/**
 * The bundle a render host shows. `main` and `preview` name files in
 * `files`, and `absent` lists the targets read without a current result.
 */
export interface RenderRecord {
  readonly render: string;
  readonly bundle: string;
  readonly main: string;
  readonly preview: string | null;
  readonly files: readonly RenderFileRecord[];
  readonly warnings: readonly ProjectDiagnostic[];
  readonly absent: readonly string[];
}

interface Presented {
  readonly element: HTMLElement;
  resize(width: number): void;
  destroy(): void;
}

const PAGE_WIDTH = 920;
const PAGE_GUTTER = 16;

const STYLE = `
:host { display: block; }
:host([hidden]) { display: none; }
.toolbar { display: flex; gap: 12px; align-items: center; justify-content: flex-end;
  min-height: 1.4em; padding: 4px 0; font: 12px/1.4 system-ui, sans-serif;
  color: color-mix(in srgb, CanvasText 68%, transparent); }
.toolbar a { color: inherit; }
.toolbar a[hidden] { display: none; }
.problems { font: 13px/1.5 system-ui, sans-serif; }
.problems article { margin-bottom: 8px; padding: 8px 12px; border-left: 3px solid #b45309;
  background: Canvas; color: CanvasText; }
.problems article.warning { border-left-color: #a16207; }
.problems p { margin: 0; }
.problems .hint, .problems .source { color: color-mix(in srgb, CanvasText 66%, transparent); }
.content > :is(img, video) { display: block; max-width: 100%; height: auto; margin: 0 auto; }
.content > audio { display: block; width: 100%; }
.content > iframe { display: block; width: 100%; min-height: 480px; border: 0; }
.content > .note { margin: 0; font: 13px/1.5 system-ui, sans-serif; }
.pages { display: grid; gap: 16px; max-width: ${PAGE_WIDTH}px; margin: 0 auto;
  padding: 4px ${PAGE_GUTTER}px 16px; background: color-mix(in srgb, CanvasText 7%, Canvas); }
.page { position: relative; width: 100%; background: white;
  box-shadow: 0 1px 3px rgb(0 0 0 / 0.16), 0 0 0 1px rgb(0 0 0 / 0.05); }
.page canvas { display: block; width: 100%; height: 100%; }
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

const fileName = (path: string): string => path.split("/").at(-1) ?? path;

const majorType = (mediaType: string): string => mediaType.split("/", 1)[0] ?? "";

const presentable = (file: RenderFileRecord): boolean =>
  file.mediaType === "application/pdf" ||
  file.mediaType === "text/html" ||
  ["image", "video", "audio"].includes(majorType(file.mediaType));

const presentPdf = async (
  file: RenderFileRecord,
  width: number,
  signal: AbortSignal,
): Promise<Presented> => {
  const response = await fetch(file.url, { signal });
  if (!response.ok) {
    throw new Error(`${fileName(file.path)} could not be loaded (${response.status}).`);
  }
  const pages = await openPdf(new Uint8Array(await response.arrayBuffer()), width, signal);
  const element = document.createElement("div");
  element.className = "pages";
  element.append(...pages.pages);
  return {
    element,
    resize: (layout) => pages.resize(layout),
    destroy: () => pages.destroy(),
  };
};

const presentImage = async (file: RenderFileRecord, alt: string): Promise<Presented> => {
  const image = document.createElement("img");
  image.alt = alt;
  image.src = file.url;
  // Decoding first keeps the previous bundle on screen until this one paints.
  await image.decode();
  return { element: image, resize: () => {}, destroy: () => {} };
};

const presentMedia = (file: RenderFileRecord, poster: RenderFileRecord | undefined): Presented => {
  const media = document.createElement(majorType(file.mediaType) === "video" ? "video" : "audio");
  media.controls = true;
  media.preload = "metadata";
  // The file route serves byte ranges, so the browser seeks without loading
  // the whole file.
  media.src = file.url;
  if (media instanceof HTMLVideoElement && poster) {
    media.poster = poster.url;
  }
  return {
    element: media,
    resize: () => {},
    destroy: () => {
      media.removeAttribute("src");
      media.load();
    },
  };
};

const presentHtml = (file: RenderFileRecord, title: string): Presented => {
  const frame = document.createElement("iframe");
  // An opaque origin keeps generated HTML away from the page and its
  // projection authority.
  frame.setAttribute("sandbox", "allow-scripts");
  frame.title = title;
  frame.src = file.url;
  return { element: frame, resize: () => {}, destroy: () => {} };
};

const presentFile = (
  file: RenderFileRecord,
  record: RenderRecord,
  poster: RenderFileRecord | undefined,
  width: number,
  signal: AbortSignal,
): Promise<Presented> | Presented => {
  if (file.mediaType === "application/pdf") {
    return presentPdf(file, width, signal);
  }
  if (file.mediaType === "text/html") {
    return presentHtml(file, record.render);
  }
  if (majorType(file.mediaType) === "image") {
    return presentImage(file, record.render);
  }
  return presentMedia(file, poster);
};

const presentNote = (main: RenderFileRecord): Presented => {
  const note = document.createElement("p");
  note.className = "note";
  note.textContent = `${fileName(main.path)} is ready to download.`;
  return { element: note, resize: () => {}, destroy: () => {} };
};

/**
 * Show a render's main file by its media type: PDF pages, an image, a video
 * with its preview as poster, audio, or HTML in a sandboxed frame. Another
 * main file shows its preview when it has a presentable one, and the toolbar
 * always links the main file for download.
 */
const present = async (
  record: RenderRecord,
  width: number,
  signal: AbortSignal,
): Promise<Presented> => {
  const file = (path: string | null) =>
    path === null ? undefined : record.files.find((item) => item.path === path);
  const main = file(record.main);
  if (!main) {
    throw new Error(`The bundle has no main file ${JSON.stringify(record.main)}.`);
  }
  const preview = file(record.preview);
  const poster = preview && majorType(preview.mediaType) === "image" ? preview : undefined;
  if (presentable(main)) {
    return presentFile(main, record, poster, width, signal);
  }
  if (preview && presentable(preview)) {
    return presentFile(preview, record, undefined, width, signal);
  }
  return presentNote(main);
};

/**
 * The toolbar, problems list, and content of one render host's shadow root.
 *
 * The stock presentation is the fallback content of the root's slot. Markup a
 * page places inside the host replaces it, and the page presents the files
 * from the host's render record itself.
 */
export class RenderView {
  private readonly status = document.createElement("span");
  private readonly download = document.createElement("a");
  private readonly problems = document.createElement("div");
  private readonly slot = document.createElement("slot");
  private readonly content = document.createElement("div");
  private shown?: Presented;
  private shownBundle?: string;
  private requested?: RenderRecord;
  // Advances with each show, so a slow presentation never replaces a newer one.
  private showing = 0;

  constructor(root: ShadowRoot) {
    const style = document.createElement("style");
    style.textContent = STYLE;
    const toolbar = document.createElement("div");
    toolbar.className = "toolbar";
    toolbar.setAttribute("part", "toolbar");
    this.status.setAttribute("role", "status");
    this.download.textContent = "Download";
    this.download.hidden = true;
    this.download.setAttribute("part", "download");
    toolbar.append(this.status, this.download);
    this.problems.className = "problems";
    this.problems.setAttribute("part", "problems");
    this.problems.setAttribute("role", "alert");
    this.content.className = "content";
    this.content.setAttribute("part", "content");
    this.slot.append(this.content);
    // Markup added to or removed from the host switches the presentation.
    this.slot.addEventListener("slotchange", () => {
      if (this.requested) {
        this.show(this.requested, new AbortController().signal).catch(() => undefined);
      }
    });
    root.replaceChildren(style, toolbar, this.problems, this.slot);
  }

  setStatus(text: string): void {
    this.status.textContent = text;
  }

  /**
   * Swap in `record` once its content is ready. Keeps the painted bundle when
   * it is the same, and presents nothing while the page supplies markup.
   */
  async show(record: RenderRecord, signal: AbortSignal): Promise<void> {
    const showing = ++this.showing;
    this.requested = record;
    this.link(record);
    if (this.slot.assignedElements().length > 0) {
      this.clear();
      return;
    }
    if (this.shown && this.shownBundle === record.bundle) {
      return;
    }
    const shown = await present(record, this.width(), signal);
    if (signal.aborted || showing !== this.showing) {
      shown.destroy();
      signal.throwIfAborted();
      return;
    }
    this.shown?.destroy();
    this.shown = shown;
    this.shownBundle = record.bundle;
    this.content.replaceChildren(shown.element);
  }

  private link(record: RenderRecord): void {
    const main = record.files.find((item) => item.path === record.main);
    this.download.hidden = main === undefined;
    if (main) {
      this.download.href = main.url;
      this.download.download = fileName(main.path);
    }
  }

  showProblems(diagnostics: readonly ProjectDiagnostic[]): void {
    this.problems.replaceChildren(
      ...diagnostics.map((diagnostic) => {
        const article = document.createElement("article");
        article.className = diagnostic.severity;
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
  }

  resize(): void {
    this.shown?.resize(this.width());
  }

  observedElement(): HTMLElement {
    return this.content;
  }

  /** Remove the presentation and forget the record, so markup changes show nothing. */
  destroy(): void {
    this.requested = undefined;
    this.showing += 1;
    this.clear();
  }

  private clear(): void {
    this.shown?.destroy();
    this.shown = undefined;
    this.shownBundle = undefined;
    this.content.replaceChildren();
  }

  private width(): number {
    return this.content.clientWidth > 0 ? this.content.clientWidth - 2 * PAGE_GUTTER : PAGE_WIDTH;
  }
}
