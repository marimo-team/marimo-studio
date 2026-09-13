// @deno-types="npm:@types/react@19.2.10"
import { useEffect, useRef, useState } from "react";
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist/build/pdf.mjs";

export interface PdfInstance {
  readonly blob: Blob | null;
  readonly error: string | null;
  readonly loading: boolean;
  readonly url: string | null;
}

const PDF_WORKER = new URL("./pdf.worker.min.mjs", import.meta.url).href;
const PAGE_LABELS = [
  "Executive summary",
  "Environmental profile",
  "Model evidence",
] as const;

const CanvasPdfViewer = (
  {
    instance,
    pageSummaries,
  }: {
    instance: PdfInstance;
    pageSummaries: readonly string[];
  },
) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );

  useEffect(() => {
    const container = containerRef.current;
    if (instance.blob === null || container === null) {
      setStatus("loading");
      return;
    }

    let active = true;
    const renderTasks: { cancel: () => void }[] = [];
    let destroyDocument: (() => Promise<void>) | undefined;

    const render = async () => {
      setStatus("loading");
      GlobalWorkerOptions.workerSrc = PDF_WORKER;
      const bytes = new Uint8Array(await instance.blob!.arrayBuffer());
      if (!active) {
        return;
      }
      const loadingTask = getDocument({ data: bytes });
      destroyDocument = () => loadingTask.destroy();
      const pdf = await loadingTask.promise;
      const pages = document.createDocumentFragment();

      for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
        if (!active) {
          return;
        }
        const page = await pdf.getPage(pageNumber);
        if (!active) {
          return;
        }
        const viewport = page.getViewport({ scale: 1.5 });
        const sheet = document.createElement("article");
        const summary = document.createElement("p");
        const canvas = document.createElement("canvas");
        const context = canvas.getContext("2d");
        if (context === null) {
          throw new Error("The PDF viewer requires a 2D canvas context");
        }

        sheet.className = "pdf-canvas-page";
        sheet.setAttribute(
          "data-marimo-lens-inputs",
          [
            "report-summary report-hourly report-daily",
            "report-sensors report-profile",
            "report-model report-summary",
          ][pageNumber - 1] ?? "analysis-data",
        );
        sheet.setAttribute(
          "data-marimo-lens-label",
          PAGE_LABELS[pageNumber - 1] ?? "Report page",
        );
        summary.className = "sr-only";
        summary.id = `pdf-page-${pageNumber}-summary`;
        summary.textContent = pageSummaries[pageNumber - 1] ??
          PAGE_LABELS[pageNumber - 1] ?? "Report page";
        sheet.setAttribute(
          "aria-label",
          `Page ${pageNumber} of ${pdf.numPages}: ${
            PAGE_LABELS[pageNumber - 1] ?? "Report page"
          }`,
        );
        sheet.setAttribute("aria-describedby", summary.id);
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.setAttribute("aria-hidden", "true");
        sheet.append(summary, canvas);
        pages.append(sheet);

        const task = page.render({ canvas, canvasContext: context, viewport });
        renderTasks.push(task);
        await task.promise;
      }

      if (active) {
        container.replaceChildren(pages);
        setStatus("ready");
      }
    };

    render().catch((error: unknown) => {
      if (active) {
        console.error(error);
        setStatus("error");
      }
    });

    return () => {
      active = false;
      renderTasks.forEach((task) => task.cancel());
      void destroyDocument?.().catch((error: unknown) => console.error(error));
    };
  }, [instance.blob, pageSummaries]);

  return (
    <>
      {instance.error || status === "error"
        ? <p className="viewer-error">The PDF preview could not be rendered.</p>
        : null}
      {instance.loading || status === "loading"
        ? (
          <p className="viewer-status">
            {instance.loading
              ? "Composing three A4 pages"
              : "Rendering PDF preview"}
          </p>
        )
        : null}
      <div
        ref={containerRef}
        className="pdf-canvas-viewer"
        aria-busy={status === "loading"}
        aria-label="Scrollable three-page PDF preview"
        role="region"
        tabIndex={0}
      />
    </>
  );
};

export const ReportViewer = ({
  instance,
  pageSummaries,
}: {
  instance: PdfInstance;
  pageSummaries: readonly string[];
}) => <CanvasPdfViewer instance={instance} pageSummaries={pageSummaries} />;
