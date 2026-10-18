// Render the example wall, in every theme, to apps/docs/public/showcase/.
// Usage: node tools/example-showcase/render.ts
import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import {
  documentationExampleFamilies,
  documentationExamplePages,
  documentationExampleWall,
} from "../../apps/docs/examples.ts";

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
// Route-served pages give the encoder a same-origin URL for the capture.
const encoderOrigin = "http://showcase.invalid";

const name = "marimo-studio-wall";
const themes = ["light", "dark"] as const;
const canvas = { height: 1360, width: 2400 };
// Where the plane sits in front of the camera, in canvas pixels.
const camera = { x: 10, y: -60, z: -1820 };
// Each output is written as NAME-THEME{suffix}.webp at canvas.width * scale.
// WebP quality runs from 0 to 1, and Chromium encodes quality 1 losslessly.
const outputs = [
  { quality: 1, scale: 2, suffix: "@2x" },
  { quality: 0.9, scale: 1, suffix: "" },
] as const;
const supersample = 2;

const columns = documentationExampleFamilies.map((family) =>
  documentationExamplePages(family).map((page) => ({
    ...page,
    shot: `shots/${page.path.replace("/", "--")}.png`,
  })),
);
const missing = columns
  .flat()
  .filter(({ shot }) => !existsSync(join(here, shot)))
  .map(({ path }) => path);
if (missing.length > 0) {
  throw new Error(
    `Missing shots. Capture them with node tools/example-showcase/capture.ts ${missing.join(" ")}`,
  );
}

// Outputs run largest first, so each smaller output resamples the previous one
// in steps close to 2x, where Chromium's high-quality filter matches Lanczos.
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
  for (const theme of themes) {
    // The capture keeps a transparent background, so card shadows keep their alpha.
    const page = await browser.newPage({
      deviceScaleFactor: outputs[0].scale * supersample,
      viewport: canvas,
    });
    await page.addInitScript((wall: unknown) => Object.assign(window, { wall }), {
      camera,
      columns,
      geometry: documentationExampleWall,
      height: canvas.height,
      theme,
    });
    await page.goto(pathToFileURL(join(here, "compose.html")).href);
    await page.waitForSelector("body[data-ready=true]", { timeout: 60_000 });
    capture = await page.locator("#canvas").screenshot({ omitBackground: true });
    await page.close();
    const encoded: string[] = await encoder.evaluate(
      encode,
      outputs.map(({ quality, scale }) => ({ quality, width: canvas.width * scale })),
    );
    for (const [index, { suffix }] of outputs.entries()) {
      await writeFile(
        join(outDir, `${name}-${theme}${suffix}.webp`),
        Buffer.from(encoded[index] ?? "", "base64"),
      );
    }
    console.log(`rendered ${name}-${theme}`);
  }
} finally {
  await browser.close();
}
