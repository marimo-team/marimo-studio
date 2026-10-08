import initPdf, { render } from "takumi-pdf/no-init";

import { OccupancyReport } from "./OccupancyReport.tsx";
import type { OccupancyAnalysis } from "./types.ts";

// Takumi's renderer is a WebAssembly module. The view loads the published
// build from jsDelivr and checks it against this digest.
const TAKUMI_WASM = "https://cdn.jsdelivr.net/npm/takumi-pdf@0.11.0/pkg/takumi_pdf_wasm_bg.wasm";
const TAKUMI_WASM_INTEGRITY = "sha384-okz9r1n/F+k/358kBqCQfT7J96Z+drP3zt54tICcXUCT/Ki6ccESa5aOCqVDCvVx";

const FONT_WEIGHTS = ["Regular", "Medium", "SemiBold", "Bold"] as const;

/** Inter files shipped in `public/fonts`, resolved against the published page. */
export const fontUrl = (weight: (typeof FONT_WEIGHTS)[number]) =>
  new URL(`./fonts/Inter-${weight}.ttf`, document.baseURI).href;

let ready: Promise<{ name: string; data: ArrayBuffer }[]> | undefined;

const prepare = () => {
  ready ??= (async () => {
    await initPdf({ module_or_path: fetch(TAKUMI_WASM, { integrity: TAKUMI_WASM_INTEGRITY }) });
    return Promise.all(FONT_WEIGHTS.map(async (weight) => {
      const response = await fetch(fontUrl(weight));
      if (!response.ok) throw new Error(`Inter ${weight} is unavailable (${response.status})`);
      return { name: "Inter", data: await response.arrayBuffer() };
    }));
  })();
  return ready;
};

/** Render the three-page report for one `occupancy_analysis` snapshot. */
export const renderReport = async (analysis: OccupancyAnalysis): Promise<Blob> => {
  const fonts = await prepare();
  const pdf = await render(<OccupancyReport analysis={analysis} />, { fonts, margin: 0, size: "a4" });
  return new Blob([pdf.slice()], { type: "application/pdf" });
};
