// Compose each figure in figures.json from the captured shots and write it in
// every theme to apps/docs/public/figures/. Usage: node scripts/example-figure/render.ts
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

interface Figure {
  name: string;
  // Notebook cells in notebook order.
  cells: string[];
}

// Playwright loads untyped from the docs workspace, so name the route surface in use.
interface EncoderRoute {
  request(): { url(): string };
  fulfill(response: { body: Buffer | string; contentType: string }): Promise<void>;
}

const here = import.meta.dirname;
const root = resolve(here, "../..");
// The docs workspace owns the Playwright dependency and its Chromium install.
const require = createRequire(join(root, "apps/docs/package.json"));
const { chromium } = require("@playwright/test");
const shotsDir = join(here, "shots");
const outDir = join(root, "apps/docs/public/figures");
const themes = ["light", "dark"];
// The wide layout sets three cards in a row for READMEs and desktop pages.
// The narrow layout stacks them for phone widths.
const layouts = [
  { name: "wide", width: 1200 },
  { name: "narrow", width: 440 },
];
// The canvas is rasterized at `supersample` times the output scale, then
// resampled once, so small text in the scaled screenshots stays sharp.
const outputScale = 2;
const supersample = 2;
const quality = 0.92;
// Route-served pages give the encoder a same-origin URL for the capture.
const encoderOrigin = "http://figure.invalid";

const { figures } = JSON.parse(await readFile(join(here, "figures.json"), "utf8")) as {
  figures: Figure[];
};
const notebookFile = join(shotsDir, "notebook.json");
const shots = figures.flatMap(({ cells, name }) => [
  ...cells.map((cell) => `cell--${cell}.png`),
  `${name}-page.png`,
  `${name}-report.png`,
]);
const missing = [notebookFile, ...shots.map((shot) => join(shotsDir, shot))].filter(
  (file) => !existsSync(file),
);
if (missing.length > 0) {
  throw new Error(
    `Missing shots: ${missing.join(", ")}. Capture them with node scripts/example-figure/capture.ts`,
  );
}
const { order } = JSON.parse(await readFile(notebookFile, "utf8")) as { order: string[] };

// Resample the supersampled capture with Chromium's high-quality filter and
// encode it as WebP. Transparent card shadows keep their alpha.
const encode = async ({ quality, width }: { quality: number; width: number }): Promise<string> => {
  const capture = await createImageBitmap(await (await fetch("/capture.png")).blob());
  const image = await createImageBitmap(capture, {
    premultiplyAlpha: "premultiply",
    resizeHeight: Math.round((capture.height * width) / capture.width),
    resizeQuality: "high",
    resizeWidth: width,
  });
  const canvas = new OffscreenCanvas(image.width, image.height);
  canvas.getContext("2d")?.drawImage(image, 0, 0);
  const blob = await canvas.convertToBlob({ quality, type: "image/webp" });
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
};

await mkdir(outDir, { recursive: true });
const browser = await chromium.launch();
try {
  let capture = Buffer.alloc(0);
  const encoder = await browser.newPage();
  await encoder.route(`${encoderOrigin}/**`, (route: EncoderRoute) =>
    route.request().url().endsWith("/capture.png")
      ? route.fulfill({ body: capture, contentType: "image/png" })
      : route.fulfill({ body: "<!doctype html>", contentType: "text/html" }),
  );
  await encoder.goto(`${encoderOrigin}/`);
  for (const figure of figures) {
    for (const [layout, theme] of layouts.flatMap((layout) =>
      themes.map((theme) => [layout, theme] as const),
    )) {
      const url = pathToFileURL(join(here, "compose.html"));
      url.search = new URLSearchParams({
        layout: layout.name,
        theme,
        width: String(layout.width),
      }).toString();
      const page = await browser.newPage({
        deviceScaleFactor: outputScale * supersample,
        viewport: { height: 900, width: layout.width },
      });
      await page.addInitScript((value: unknown) => Object.assign(window, { composition: value }), {
        figure,
        notebook: "quadratic_program.py",
        order,
      });
      await page.goto(url.href);
      await page.waitForSelector("body[data-ready=true]", { timeout: 60_000 });
      capture = await page.locator("#canvas").screenshot({ omitBackground: true });
      await page.close();
      const encoded: string = await encoder.evaluate(encode, {
        quality,
        width: layout.width * outputScale,
      });
      const name = `${figure.name}-${layout.name}-${theme}`;
      await writeFile(join(outDir, `${name}.webp`), Buffer.from(encoded, "base64"));
      console.log(`rendered ${name}`);
    }
  }
} finally {
  await browser.close();
}
