import type * as PdfJs from "pdfjs-dist";

interface PdfEngine {
  readonly pdfjs: typeof PdfJs;
  readonly worker: PdfJs.PDFWorker;
}

interface PendingPage {
  readonly page: PdfJs.PDFPageProxy;
  readonly scale: number;
}

/** Laid-out pages of one document, released together when it is replaced. */
export interface DocumentPages {
  readonly pages: readonly HTMLElement[];
  /** Keep the text layers aligned when the pages are laid out at `width`. */
  resize(width: number): void;
  destroy(): void;
}

const MAX_PIXEL_RATIO = 2;

let engine: Promise<PdfEngine> | undefined;

// Presentation frames have an opaque origin, so the pdf.js engine runs from a
// data URL in the same way as the WebAssembly notebook worker. Every document
// shares this one worker. Passing it to getDocument keeps a destroyed loading
// task from terminating it.
const loadEngine = (): Promise<PdfEngine> => {
  if (engine) {
    return engine;
  }
  const loading = Promise.all([import("pdfjs-dist"), import("./pdf-engine-source.ts")]).then(
    ([pdfjs, source]) => ({
      pdfjs,
      worker: pdfjs.PDFWorker.create({
        name: "marimo-studio-pdf",
        port: new Worker(
          `data:text/javascript;charset=utf-8,${encodeURIComponent(source.default)}`,
          {
            type: "module",
            name: "marimo-studio-pdf",
          },
        ),
      }),
    }),
  );
  // A failed chunk load leaves the next document free to retry.
  loading.catch(() => {
    if (engine === loading) {
      engine = undefined;
    }
  });
  engine = loading;
  return loading;
};

const paintPage = async (
  pdfjs: typeof PdfJs,
  { page, scale }: PendingPage,
  container: Element,
): Promise<void> => {
  const viewport = page.getViewport({ scale });
  const ratio = Math.min(globalThis.devicePixelRatio || 1, MAX_PIXEL_RATIO);
  const pixels = page.getViewport({ scale: scale * ratio });
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(pixels.width);
  canvas.height = Math.ceil(pixels.height);
  const text = document.createElement("div");
  text.className = "textLayer";
  container.replaceChildren(canvas, text);
  await page.render({ canvas, viewport: pixels }).promise;
  await new pdfjs.TextLayer({
    textContentSource: page.streamTextContent(),
    container: text,
    viewport,
  }).render();
  page.cleanup();
};

/**
 * Lay out every page of a PDF at `width`, then paint each page with a
 * selectable text layer as it nears the viewport.
 */
export const openPdf = async (
  data: Uint8Array,
  width: number,
  signal: AbortSignal,
): Promise<DocumentPages> => {
  const { pdfjs, worker } = await loadEngine();
  signal.throwIfAborted();
  const task = pdfjs.getDocument({ data, worker });
  const abort = () => void task.destroy();
  signal.addEventListener("abort", abort, { once: true });
  try {
    const pdf = await task.promise;
    const pages = await Promise.all(
      Array.from({ length: pdf.numPages }, (_, index) => pdf.getPage(index + 1)),
    );
    signal.throwIfAborted();
    const containers: HTMLElement[] = [];
    const widths = new Map<HTMLElement, number>();
    const pending = new Map<Element, PendingPage>();
    for (const page of pages) {
      const natural = page.getViewport({ scale: 1 });
      const scale = width / natural.width;
      const container = document.createElement("div");
      container.className = "page";
      container.style.setProperty("--total-scale-factor", String(scale));
      container.style.aspectRatio = `${natural.width} / ${natural.height}`;
      containers.push(container);
      widths.set(container, natural.width);
      pending.set(container, { page, scale });
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const { isIntersecting, target } of entries) {
          const page = pending.get(target);
          if (!isIntersecting || !page) {
            continue;
          }
          pending.delete(target);
          observer.unobserve(target);
          // Destroying the document rejects paints still in flight.
          void paintPage(pdfjs, page, target).catch(() => {});
        }
      },
      { rootMargin: "100% 0px" },
    );
    containers.forEach((container) => observer.observe(container));
    return {
      pages: containers,
      // Pages scale with their container. Text layers size their glyphs from
      // the scale factor, so it follows the laid-out width.
      resize: (layout) => {
        for (const [container, natural] of widths) {
          container.style.setProperty("--total-scale-factor", String(layout / natural));
        }
      },
      destroy: () => {
        observer.disconnect();
        void task.destroy();
      },
    };
  } catch (error) {
    await task.destroy();
    throw error;
  } finally {
    signal.removeEventListener("abort", abort);
  }
};
