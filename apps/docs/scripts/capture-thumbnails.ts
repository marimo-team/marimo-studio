import { chromium, type Browser, type Page } from "@playwright/test";
import { mkdir, stat, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { preview } from "vite";

import { documentationExampleFamilies, documentationPosterViewports } from "../examples.ts";
import { selectDocumentationExamples } from "./example-selection.ts";

const packageRoot = dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
const thumbnailRoot = join(packageRoot, "public", "thumbnails");
const posterRoot = join(packageRoot, "public", "posters");
const viewport = { height: 900, width: 1440 };
const thumbnailWidth = 1600;
const posterWidth = 1024;
const quality = 0.86;
const settleMs = 1500;
const timeoutMs = 60_000;

const usage = `Usage: pnpm --filter @marimo-studio/docs thumbnails [selectors] [--base-url URL]

Captures the Examples gallery image and the landing-page poster for each view
from the exported examples in public/examples. Writes
public/thumbnails/FAMILY/VIEW.webp and public/posters/FAMILY/VIEW.webp. Run
\`make docs-thumbnails\` to export missing examples and install Chromium first.

Selectors may be repeated. Without selectors every view is captured:
  --family SLUG       Capture every view of one family
  --view FAMILY/VIEW  Capture one view
  --base-url URL      Capture from a running docs site instead of public/`;

/** Wait until the view has fetched its data, loaded its fonts, and settled. */
const waitForView = async (page: Page, url: string): Promise<void> => {
  const response = await page.goto(url, { timeout: timeoutMs, waitUntil: "load" });
  if (!response?.ok()) {
    throw new Error(`${url} responded with ${response?.status() ?? "no response"}.`);
  }
  await page.waitForLoadState("networkidle", { timeout: timeoutMs });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(settleMs);
};

/** Chromium resamples the capture and encodes WebP, so no image library is required. */
const encodeWebp = async (encoder: Page, png: Buffer, outputWidth: number): Promise<Buffer> => {
  const encoded = await encoder.evaluate(
    async ({ data, quality, width }) => {
      const source = await createImageBitmap(await (await fetch(data)).blob());
      const height = Math.round((source.height * width) / source.width);
      const image = await createImageBitmap(source, {
        resizeHeight: height,
        resizeQuality: "high",
        resizeWidth: width,
      });
      const canvas = new OffscreenCanvas(width, height);
      canvas.getContext("2d")?.drawImage(image, 0, 0);
      const blob = await canvas.convertToBlob({ quality, type: "image/webp" });
      let binary = "";
      for (const byte of new Uint8Array(await blob.arrayBuffer())) {
        binary += String.fromCharCode(byte);
      }
      return btoa(binary);
    },
    { data: `data:image/png;base64,${png.toString("base64")}`, quality, width: outputWidth },
  );
  return Buffer.from(encoded, "base64");
};

const write = async (path: string, image: Buffer): Promise<void> => {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, image);
};

const capture = async (browser: Browser, baseUrl: string, selectors: string[]) => {
  const selection = selectDocumentationExamples(documentationExampleFamilies, selectors);
  const context = await browser.newContext({
    deviceScaleFactor: 2,
    reducedMotion: "reduce",
    viewport,
  });
  const encoder = await browser.newPage();
  const failed: string[] = [];
  try {
    for (const { family, views } of selection.families) {
      for (const view of views) {
        const name = `${family.slug}/${view.key}`;
        const page = await context.newPage();
        page.on("pageerror", (error) => console.warn(`  ${name} reported: ${error.message}`));
        try {
          await waitForView(page, new URL(`examples/${name}/index.html`, baseUrl).href);
          const thumbnail = await page.screenshot({ type: "png" });
          await write(
            join(thumbnailRoot, family.slug, `${view.key}.webp`),
            await encodeWebp(encoder, thumbnail, thumbnailWidth),
          );
          // Posters reflow the same page at their own viewport so reports show
          // more of their scroll and apps keep a single screen.
          await page.setViewportSize(documentationPosterViewports[view.poster]);
          await page.waitForTimeout(settleMs);
          const poster = await page.screenshot({ type: "png" });
          await write(
            join(posterRoot, family.slug, `${view.key}.webp`),
            await encodeWebp(encoder, poster, posterWidth),
          );
          console.log(`Captured ${name}`);
        } catch (error) {
          failed.push(name);
          console.error(
            `Could not capture ${name}: ${error instanceof Error ? error.message : String(error)}`,
          );
        } finally {
          await page.close();
        }
      }
    }
  } finally {
    await context.close();
  }
  return failed;
};

const parseArguments = (arguments_: string[]) => {
  // pnpm forwards the `--` that separates its own options from script options.
  const values = arguments_[0] === "--" ? arguments_.slice(1) : arguments_;
  if (values.includes("--help") || values.includes("-h")) {
    return undefined;
  }
  const baseIndex = values.indexOf("--base-url");
  if (baseIndex < 0) {
    return { baseUrl: undefined, selectors: values };
  }
  const baseUrl = values[baseIndex + 1];
  if (!baseUrl) {
    throw new Error("--base-url requires a URL.");
  }
  return {
    baseUrl: new URL(baseUrl).href,
    selectors: [...values.slice(0, baseIndex), ...values.slice(baseIndex + 2)],
  };
};

const main = async (): Promise<void> => {
  const options = parseArguments(process.argv.slice(2));
  if (!options) {
    console.log(usage);
    return;
  }
  if (!options.baseUrl) {
    try {
      await stat(join(packageRoot, "public", "examples"));
    } catch {
      throw new Error("public/examples is missing. Run `make docs-examples` first.");
    }
  }
  // Serve public/ the way the docs site publishes it, so exported views load
  // their workers, modules, and sibling assets over HTTP.
  const server = options.baseUrl
    ? undefined
    : await preview({
        build: { outDir: "public" },
        configFile: false,
        logLevel: "silent",
        preview: { host: "127.0.0.1", port: 0 },
        root: packageRoot,
      });
  let browser: Browser | undefined;
  try {
    const baseUrl = options.baseUrl ?? server?.resolvedUrls?.local[0];
    if (!baseUrl) {
      throw new Error("The thumbnail server did not report a local URL.");
    }
    browser = await chromium.launch();
    const failed = await capture(browser, baseUrl, options.selectors);
    if (failed.length > 0) {
      throw new Error(`Could not capture ${failed.join(", ")}.`);
    }
  } finally {
    await browser?.close();
    await server?.close();
  }
};

main().catch((error: Error) => {
  console.error(error.message);
  process.exitCode = 1;
});
