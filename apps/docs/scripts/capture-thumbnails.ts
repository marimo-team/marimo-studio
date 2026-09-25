import { chromium, type Browser, type Page } from "@playwright/test";
import { mkdir, stat, writeFile } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { preview } from "vite";

import { documentationExampleFamilies } from "../examples.ts";
import { selectDocumentationExamples } from "./example-selection.ts";

const packageRoot = dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
const formats = ["webp", "png", "jpeg"] as const;
const themes = ["light", "dark"] as const;
// WebP stores each dimension in 14 bits.
const webpMaxDimension = 16_383;
type Format = (typeof formats)[number];
type Theme = (typeof themes)[number];

interface Shape {
  format: Format;
  fullPage: boolean;
  height: number;
  maxHeight: number;
  /** Resize to this many pixels wide. Undefined keeps the device-pixel width. */
  outputWidth: number | undefined;
  quality: number;
  scale: number;
  width: number;
}

const presetNames = ["card", "tall"] as const;
type PresetName = (typeof presetNames)[number];

const presets: Record<PresetName, Shape> = {
  card: {
    format: "webp",
    fullPage: false,
    height: 900,
    maxHeight: 900,
    outputWidth: 1600,
    quality: 86,
    scale: 2,
    width: 1440,
  },
  tall: {
    format: "webp",
    fullPage: true,
    height: 900,
    maxHeight: 2400,
    outputWidth: 1600,
    quality: 90,
    scale: 2,
    width: 1280,
  },
};

const describeShape = (shape: Shape): string => {
  const page = shape.fullPage
    ? `${shape.width}px wide, full page up to ${shape.maxHeight}px`
    : `${shape.width}x${shape.height} viewport`;
  const output = shape.outputWidth ? `${shape.outputWidth}px wide` : "native width";
  const format = shape.format === "png" ? "png" : `${shape.format} q${shape.quality}`;
  return `${page} at ${shape.scale}x, ${output} ${format}`;
};

const usage = `Usage: pnpm --filter @marimo-studio/docs thumbnails [options]

Captures one image per documentation example view from the published examples
in public/examples. Run \`make docs-examples\` first, or pass --base-url. Capture
uses Playwright's Chromium: run \`make docs-thumbnails\`, or
\`pnpm --filter @marimo-studio/docs install-browser\` before this script.

Presets set every capture and output option. Flags override single values:
${presetNames.map((name) => `  ${name.padEnd(22)}${describeShape(presets[name])}`).join("\n")}

Selectors, repeatable. Without selectors every view is captured:
  --family SLUG         Capture every view of one family
  --view FAMILY/VIEW    Capture one view

Capture:
  --preset NAME         ${presetNames.join(" or ")} (default card)
  --width PX            Viewport width in CSS pixels
  --height PX           Viewport height in CSS pixels
  --scale N             Device pixel ratio
  --full-page           Capture the document height instead of the viewport
  --no-full-page        Capture the viewport only
  --max-height PX       Clip full-page captures to this CSS height
  --theme light|dark    Preferred color scheme reported to the view (default light)
  --settle MS           Wait after the network goes idle (default 1500)
  --timeout MS          Readiness timeout per view (default 60000)
  --base-url URL        Capture from a running docs site instead of public/

Output:
  --format webp|png|jpeg  Image format
  --quality 1-100         WebP and JPEG quality
  --output-width PX       Resize to this width, or "native" for device pixels
  --out DIR               Output root (default public/thumbnails/PRESET)

Images are written to DIR/FAMILY/VIEW.FORMAT. Full-page captures grow the
viewport when a main panel scrolls inside it, then scroll the view once so
lazy and scroll-revealed content renders. Views that fill a fixed viewport,
such as slide decks and maps, capture one viewport.`;

interface Options extends Shape {
  baseUrl: string | undefined;
  out: string;
  preset: PresetName;
  selectors: string[];
  settle: number;
  theme: Theme;
  timeout: number;
}

const number = (flag: string, value: string | undefined, fallback: number, min = 1): number => {
  if (value === undefined) {
    return fallback;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < min) {
    throw new RangeError(`--${flag} must be a number of at least ${min}, received ${value}.`);
  }
  return parsed;
};

const choice = <T extends string>(
  flag: string,
  value: string | undefined,
  allowed: readonly T[],
): T | undefined => {
  const selected = allowed.find((candidate) => candidate === value);
  if (value !== undefined && selected === undefined) {
    throw new Error(`--${flag} must be one of ${allowed.join(", ")}, received ${value}.`);
  }
  return selected;
};

const parseOutputWidth = (value: string | undefined, fallback: number | undefined) => {
  if (value === undefined) {
    return fallback;
  }
  return value === "native" ? undefined : number("output-width", value, 1);
};

const outputSize = (shape: Shape, cssHeight: number) => {
  const width = shape.outputWidth ?? Math.round(shape.width * shape.scale);
  return { height: Math.round((cssHeight * width) / shape.width), width };
};

const parseOptions = (arguments_: string[]): Options | undefined => {
  const { values } = parseArgs({
    allowNegative: true,
    // pnpm forwards the `--` that separates its own options from script options.
    args: arguments_[0] === "--" ? arguments_.slice(1) : arguments_,
    options: {
      "base-url": { type: "string" },
      family: { type: "string", multiple: true },
      format: { type: "string" },
      "full-page": { type: "boolean" },
      height: { type: "string" },
      help: { type: "boolean", short: "h" },
      "max-height": { type: "string" },
      out: { type: "string" },
      "output-width": { type: "string" },
      preset: { type: "string" },
      quality: { type: "string" },
      scale: { type: "string" },
      settle: { type: "string" },
      theme: { type: "string" },
      timeout: { type: "string" },
      view: { type: "string", multiple: true },
      width: { type: "string" },
    },
    strict: true,
  });
  if (values.help) {
    return undefined;
  }
  const preset = choice("preset", values.preset, presetNames) ?? "card";
  const base = presets[preset];
  const shape: Shape = {
    format: choice("format", values.format, formats) ?? base.format,
    fullPage: values["full-page"] ?? base.fullPage,
    height: number("height", values.height, base.height),
    maxHeight: number("max-height", values["max-height"], base.maxHeight),
    outputWidth: parseOutputWidth(values["output-width"], base.outputWidth),
    quality: number("quality", values.quality, base.quality),
    scale: number("scale", values.scale, base.scale, 0.25),
    width: number("width", values.width, base.width),
  };
  if (shape.quality > 100) {
    throw new RangeError(`--quality must be at most 100, received ${shape.quality}.`);
  }
  const largest = outputSize(shape, shape.fullPage ? shape.maxHeight : shape.height);
  if (shape.format === "webp" && Math.max(largest.width, largest.height) > webpMaxDimension) {
    throw new RangeError(
      `WebP images are limited to ${webpMaxDimension} px, and these options can produce ${largest.width}x${largest.height}. Lower --max-height, --scale, or --output-width, or use --format png.`,
    );
  }
  return {
    ...shape,
    baseUrl: values["base-url"] && new URL(values["base-url"]).href,
    out: resolve(values.out ?? join(packageRoot, "public", "thumbnails", preset)),
    preset,
    selectors: [
      ...(values.family ?? []).flatMap((slug) => ["--family", slug]),
      ...(values.view ?? []).flatMap((view) => ["--view", view]),
    ],
    settle: number("settle", values.settle, 1500, 0),
    theme: choice("theme", values.theme, themes) ?? "light",
    timeout: number("timeout", values.timeout, 60_000),
  };
};

/**
 * Return how far the largest inner scroll container overflows. App-shaped views
 * fill the viewport and scroll a main panel, so their document height does not
 * describe their content.
 */
const panelOverflow = (page: Page): Promise<number> =>
  page.evaluate(() => {
    const viewportArea = window.innerWidth * window.innerHeight;
    let overflow = 0;
    for (const element of document.body.querySelectorAll("*")) {
      const { overflowY } = getComputedStyle(element);
      const bounds = element.getBoundingClientRect();
      if (
        (overflowY === "auto" || overflowY === "scroll") &&
        bounds.width * bounds.height > viewportArea / 2
      ) {
        overflow = Math.max(overflow, element.scrollHeight - element.clientHeight);
      }
    }
    return overflow;
  });

/** Grow the viewport until the main panel shows its full content or reaches the height limit. */
const fitPanel = async (page: Page, options: Options): Promise<void> => {
  let height = options.height;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const overflow = await panelOverflow(page);
    const next = Math.min(height + overflow, options.maxHeight);
    if (overflow <= 1 || next === height) {
      return;
    }
    height = next;
    await page.setViewportSize({ height, width: options.width });
    await page.waitForTimeout(300);
  }
};

/** Wait until the view has fetched its data, loaded its fonts, and finished its entrance. */
const waitForView = async (page: Page, url: string, options: Options): Promise<void> => {
  const response = await page.goto(url, { timeout: options.timeout, waitUntil: "load" });
  if (!response?.ok()) {
    throw new Error(`${url} responded with ${response?.status() ?? "no response"}.`);
  }
  await page.waitForLoadState("networkidle", { timeout: options.timeout });
  await page.evaluate(() => document.fonts.ready);
  if (options.fullPage) {
    await fitPanel(page, options);
    // Lazy images, intersection observers, and scroll-driven sections render
    // only after they have entered the viewport once.
    await page.evaluate(
      async ({ limit, step }) => {
        const root = document.scrollingElement ?? document.documentElement;
        const end = Math.min(root.scrollHeight, limit);
        for (let top = 0; top < end; top += step) {
          root.scrollTo(0, top);
          await new Promise((resolveFrame) => setTimeout(resolveFrame, 150));
        }
        root.scrollTo(0, 0);
      },
      { limit: options.maxHeight, step: Math.round(options.height * 0.75) },
    );
    await page.waitForLoadState("networkidle", { timeout: options.timeout });
  }
  await page.waitForTimeout(options.settle);
};

const screenshot = async (page: Page, options: Options): Promise<Buffer> => {
  if (!options.fullPage) {
    return page.screenshot({ animations: "disabled", type: "png" });
  }
  const documentHeight = await page.evaluate(() =>
    Math.max(
      (document.scrollingElement ?? document.documentElement).scrollHeight,
      window.innerHeight,
    ),
  );
  return page.screenshot({
    animations: "disabled",
    clip: { height: Math.min(documentHeight, options.maxHeight), width: options.width, x: 0, y: 0 },
    fullPage: true,
    type: "png",
  });
};

/** Chromium encodes WebP and resamples the capture, so no image library is required. */
const encode = async (encoder: Page, png: Buffer, options: Options): Promise<Buffer> => {
  if (options.format === "png" && options.outputWidth === undefined) {
    return png;
  }
  const encoded = await encoder.evaluate(
    async ({ data, quality, type, width }) => {
      const source = await createImageBitmap(await (await fetch(data)).blob());
      const targetWidth = width ?? source.width;
      const targetHeight = Math.round((source.height * targetWidth) / source.width);
      const image =
        targetWidth === source.width
          ? source
          : await createImageBitmap(source, {
              resizeHeight: targetHeight,
              resizeQuality: "high",
              resizeWidth: targetWidth,
            });
      const canvas = new OffscreenCanvas(targetWidth, targetHeight);
      canvas.getContext("2d")?.drawImage(image, 0, 0);
      const blob = await canvas.convertToBlob({ quality: quality / 100, type });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = "";
      for (const byte of bytes) {
        binary += String.fromCharCode(byte);
      }
      return btoa(binary);
    },
    {
      data: `data:image/png;base64,${png.toString("base64")}`,
      quality: options.quality,
      type: `image/${options.format}`,
      width: options.outputWidth,
    },
  );
  return Buffer.from(encoded, "base64");
};

interface CaptureResult {
  captured: number;
  failed: string[];
}

const capture = async (
  browser: Browser,
  baseUrl: string,
  options: Options,
): Promise<CaptureResult> => {
  const selection = selectDocumentationExamples(documentationExampleFamilies, options.selectors);
  const context = await browser.newContext({
    colorScheme: options.theme,
    deviceScaleFactor: options.scale,
    reducedMotion: "reduce",
    viewport: { height: options.height, width: options.width },
  });
  const encoder = await browser.newPage();
  let captured = 0;
  const failed: string[] = [];
  try {
    for (const { family, views } of selection.families) {
      for (const view of views) {
        const name = `${family.slug}/${view.key}`;
        const page = await context.newPage();
        const problems: string[] = [];
        page.on("pageerror", (error) => problems.push(error.message));
        page.on("console", (message) => {
          if (message.type() === "error") {
            problems.push(message.text());
          }
        });
        try {
          await waitForView(page, new URL(`examples/${name}/index.html`, baseUrl).href, options);
          const image = await encode(encoder, await screenshot(page, options), options);
          const path = join(options.out, family.slug, `${view.key}.${options.format}`);
          await mkdir(dirname(path), { recursive: true });
          await writeFile(path, image);
          captured += 1;
          const shown = relative(process.cwd(), path);
          console.log(`Captured ${name} -> ${shown.startsWith("..") ? path : shown}`);
          for (const problem of problems) {
            console.warn(`  ${name} reported: ${problem}`);
          }
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
  return { captured, failed };
};

const main = async (): Promise<void> => {
  const options = parseOptions(process.argv.slice(2));
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
    const { captured, failed } = await capture(browser, baseUrl, options);
    console.log(`Captured ${captured} images with ${options.preset}: ${describeShape(options)}.`);
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
