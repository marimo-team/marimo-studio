// Capture each exported documentation notebook and view as a 3x PNG for the
// showcase compositions. Usage: node tools/example-showcase/capture.ts [FAMILY/VIEW ...]
import { createReadStream, existsSync, statSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { extname, join, resolve } from "node:path";

import { documentationExampleFamilies } from "../../apps/docs/examples.ts";

const root = resolve(import.meta.dirname, "../..");
// The docs workspace owns the Playwright dependency and its Chromium install.
const require = createRequire(join(root, "apps/docs/package.json"));
const { chromium } = require("@playwright/test");
const publicDir = join(root, "apps/docs/public");
const shotsDir = join(import.meta.dirname, "shots");
const viewport = { height: 900, width: 1440 };
const settleMs = Number(process.env.SETTLE_MS ?? 6000);
const timeoutMs = 90_000;

const contentTypes: Record<string, string> = {
  ".arrow": "application/vnd.apache.arrow.file",
  ".css": "text/css",
  ".html": "text/html",
  ".js": "text/javascript",
  ".json": "application/json",
  ".mjs": "text/javascript",
  ".parquet": "application/octet-stream",
  ".pdf": "application/pdf",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain",
  ".wasm": "application/wasm",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

const pages = documentationExampleFamilies.flatMap(({ slug, views }) =>
  ["notebook", ...views.map(({ key }) => key)].map((view) => `${slug}/${view}`),
);
const selected = process.argv.slice(2);
const unknown = selected.filter((name) => !pages.includes(name));
if (unknown.length > 0) {
  throw new Error(`Unknown example pages: ${unknown.join(", ")}. Expected FAMILY/VIEW.`);
}
if (!existsSync(join(publicDir, "examples"))) {
  throw new Error("Missing apps/docs/public/examples. Run `make docs-examples` first.");
}

const server = createServer((request, response) => {
  const path = decodeURIComponent(new URL(request.url ?? "/", "http://localhost").pathname);
  let file = join(publicDir, path);
  if (existsSync(file) && statSync(file).isDirectory()) {
    file = join(file, "index.html");
  }
  if (!file.startsWith(publicDir) || !existsSync(file)) {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, {
    "content-type": contentTypes[extname(file)] ?? "application/octet-stream",
  });
  createReadStream(file).pipe(response);
});
await new Promise<void>((listening) => server.listen(0, "127.0.0.1", listening));
const address = server.address();
const baseUrl = `http://127.0.0.1:${typeof address === "object" && address ? address.port : 0}/`;

// SwiftShader gives WebGL views such as the Field point cloud a GPU-free renderer.
const browser = await chromium.launch({
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
const context = await browser.newContext({
  deviceScaleFactor: 3,
  reducedMotion: "reduce",
  viewport,
});
await mkdir(shotsDir, { recursive: true });
try {
  for (const name of selected.length > 0 ? selected : pages) {
    const page = await context.newPage();
    page.on("pageerror", (error: Error) => console.warn(`${name}: ${error.message}`));
    const url = new URL(`examples/${name}/index.html`, baseUrl).href;
    const response = await page.goto(url, { timeout: timeoutMs, waitUntil: "load" });
    if (!response?.ok()) {
      throw new Error(`${url} responded with ${response?.status() ?? "no response"}.`);
    }
    await page.waitForLoadState("networkidle", { timeout: timeoutMs }).catch(() => {});
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(settleMs);
    await page.screenshot({ path: join(shotsDir, `${name.replace("/", "--")}.png`) });
    console.log(`captured ${name}`);
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
}
