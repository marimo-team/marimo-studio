// Render each showcase in showcases.json, in every theme, to apps/docs/public/showcase/.
// Usage: node tools/example-showcase/render.ts [NAME ...]
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { documentationExampleFamilies } from "../../apps/docs/examples.ts";

interface Showcase {
  name: string;
  layout: "fan" | "wall";
  family?: string;
  order?: [string, string, string];
  height: number;
  plane?: string;
}

// Each output is written as NAME-THEME{suffix}.webp at canvasWidth * scale.
interface ShowcaseOutput {
  suffix: string;
  scale: number;
  // WebP quality from 0 to 1. Chromium encodes quality 1 losslessly.
  quality: number;
}

interface ShowcaseConfig {
  themes: string[];
  supersample: number;
  outputs: ShowcaseOutput[];
  showcases: Showcase[];
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
const outDir = join(root, "apps/docs/public/showcase");
const canvasWidth = 2400;
// Route-served pages give the encoder a same-origin URL for the capture.
const encoderOrigin = "http://showcase.invalid";

const config = JSON.parse(await readFile(join(here, "showcases.json"), "utf8")) as ShowcaseConfig;
const selected = process.argv.slice(2);
const showcases = config.showcases.filter(
  ({ name }) => selected.length === 0 || selected.includes(name),
);
const unknown = selected.filter(
  (name) => !config.showcases.some((showcase) => showcase.name === name),
);
if (unknown.length > 0) {
  throw new Error(`Unknown showcases: ${unknown.join(", ")}.`);
}

// Card headers read notebook files, view labels, and technologies from the docs catalog.
const catalog = Object.fromEntries(
  documentationExampleFamilies.map(({ notebook, slug, views }) => [
    slug,
    {
      notebook: notebook.split("/").at(-1),
      views: views.map(({ key, label, technologies }) => ({
        key,
        label,
        technologies: technologies.map(({ name }) => name),
      })),
    },
  ]),
);

// compose.html renders an empty card for a missing shot, so check the shots
// each selected showcase uses: a fan uses its family, the wall uses them all.
const familyPages = (slug: string): string[] => {
  const family = documentationExampleFamilies.find((entry) => entry.slug === slug);
  if (!family) {
    throw new Error(`Unknown example family: ${slug}.`);
  }
  return ["notebook", ...family.views.map(({ key }) => key)].map((view) => `${slug}/${view}`);
};
const pages = new Set(
  showcases.flatMap((showcase) =>
    showcase.layout === "wall"
      ? documentationExampleFamilies.flatMap(({ slug }) => familyPages(slug))
      : familyPages(showcase.family ?? ""),
  ),
);
const missing = [...pages].filter(
  (page) => !existsSync(join(here, "shots", `${page.replace("/", "--")}.png`)),
);
if (missing.length > 0) {
  throw new Error(
    `Missing shots. Capture them with node tools/example-showcase/capture.ts ${missing.join(" ")}`,
  );
}

// Largest output first, so each smaller output resamples the previous one in
// steps close to 2x, where Chromium's high-quality filter matches Lanczos.
const outputs = [...config.outputs].sort((left, right) => right.scale - left.scale);
const renderScale = (outputs[0]?.scale ?? 1) * config.supersample;

// Resample the supersampled capture with Chromium's high-quality filter and
// encode each target as WebP. Transparent card shadows keep their alpha.
const encode = async (targets: { quality: number; width: number }[]): Promise<string[]> => {
  let image = await createImageBitmap(await (await fetch("/capture.png")).blob());
  const encoded: string[] = [];
  for (const { quality, width } of targets) {
    image = await createImageBitmap(image, {
      premultiplyAlpha: "premultiply",
      resizeHeight: Math.round((image.height * width) / image.width),
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
    encoded.push(btoa(binary));
  }
  return encoded;
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
  for (const showcase of showcases) {
    for (const theme of config.themes) {
      const url = pathToFileURL(join(here, "compose.html"));
      const query: Record<string, string> = {
        bg: "transparent",
        h: String(showcase.height),
        layout: showcase.layout,
        theme,
      };
      if (showcase.family) query.family = showcase.family;
      if (showcase.order) query.order = showcase.order.join(",");
      if (showcase.plane) query.plane = showcase.plane;
      url.search = new URLSearchParams(query).toString();
      const page = await browser.newPage({
        deviceScaleFactor: renderScale,
        viewport: { height: showcase.height, width: canvasWidth },
      });
      await page.addInitScript(
        (value: unknown) => Object.assign(window, { catalog: value }),
        catalog,
      );
      await page.goto(url.href);
      await page.waitForSelector("body[data-ready=true]", { timeout: 60_000 });
      capture = await page.locator("#canvas").screenshot({ omitBackground: true });
      await page.close();
      const targets = outputs.map(({ quality, scale }) => ({
        quality,
        width: canvasWidth * scale,
      }));
      const encoded: string[] = await encoder.evaluate(encode, targets);
      for (const [index, { suffix }] of outputs.entries()) {
        const file = join(outDir, `${showcase.name}-${theme}${suffix}.webp`);
        await writeFile(file, Buffer.from(encoded[index] ?? "", "base64"));
      }
      console.log(`rendered ${showcase.name}-${theme}`);
    }
  }
} finally {
  await browser.close();
}
