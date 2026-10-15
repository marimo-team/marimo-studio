// Capture the notebook cells, HTML pages, and Typst PDFs that the example
// figures compose. Usage: node scripts/example-figure/capture.ts
//
// The capture copies examples/quadratic_program.py into a scratch workspace,
// adds each figure's view projects from views/FIGURE/, exports every view
// through `marimo-studio view export`, and opens the notebook in the marimo
// editor. render.ts composes the shots.
import { type ChildProcess, execFileSync, spawn } from "node:child_process";
import { once } from "node:events";
import { createReadStream, existsSync, rmSync, statSync } from "node:fs";
import { copyFile, cp, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { createServer as createHttpServer } from "node:http";
import { createRequire } from "node:module";
import { type AddressInfo, createServer } from "node:net";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";

interface Figure {
  name: string;
  // Notebook cells in notebook order.
  cells: string[];
}

// Playwright loads untyped from the docs workspace, so name the surface in use.
interface Page {
  goto(url: string, options: { timeout: number; waitUntil: string }): Promise<unknown>;
  waitForFunction<T>(
    script: (argument: T) => unknown,
    argument: T,
    options: { polling: number; timeout: number },
  ): Promise<unknown>;
  waitForTimeout(milliseconds: number): Promise<void>;
  evaluate<T>(script: () => T | Promise<T>): Promise<T>;
  locator(selector: string): {
    screenshot(options: { path: string }): Promise<Buffer>;
    scrollIntoViewIfNeeded(): Promise<void>;
  };
  mouse: { move(x: number, y: number): Promise<void> };
  on(event: "pageerror", listener: (error: Error) => void): void;
  context(): { close(): Promise<void> };
}

const here = import.meta.dirname;
const root = resolve(here, "../..");
// The docs workspace owns the Playwright dependency and its Chromium install.
const require = createRequire(join(root, "apps/docs/package.json"));
const { chromium } = require("@playwright/test");
const shotsDir = join(here, "shots");
const typstLibrary = join(
  root,
  "packages/marimo-studio/src/marimo_studio/view_providers/_builtin/typst/starters/default/files/marimo.typ",
);
const timeoutMs = 300_000;
const settleMs = Number(process.env.SETTLE_MS ?? 2000);
// Figure cards are about 360 CSS pixels wide. The notebook viewport is the
// narrowest at which marimo keeps each code line whole and its floating
// toolbar beside the cells. The page viewport matches the card.
const notebookViewport = { height: 1000, width: 720 };
const pageViewport = { height: 1000, width: 420 };
// The document viewer lays a page out at up to 888 CSS pixels and paints it
// at device pixel ratio 2.
const reportViewport = { height: 1200, width: 1000 };
const scale = 3;

const contentTypes: Record<string, string> = {
  ".css": "text/css",
  ".html": "text/html",
  ".js": "text/javascript",
  ".json": "application/json",
  ".mjs": "text/javascript",
  ".pdf": "application/pdf",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".wasm": "application/wasm",
  ".woff2": "font/woff2",
};

const { figures } = JSON.parse(await readFile(join(here, "figures.json"), "utf8")) as {
  figures: Figure[];
};
const cells = [...new Set(figures.flatMap((figure) => figure.cells))];
// Studio names each view after its figure and kind, such as output-value-page.
const views = figures.flatMap(({ name }) =>
  (["page", "report"] as const).map((kind) => ({
    kind,
    source: join(here, "views", name, kind),
    view: `${name}-${kind}`,
  })),
);
const missing = views.filter(({ source }) => !existsSync(join(source, "view.toml")));
if (missing.length > 0) {
  throw new Error(`Missing view projects: ${missing.map(({ source }) => source).join(", ")}.`);
}

const run = (command: string, arguments_: string[], cwd = root): string =>
  execFileSync(command, arguments_, {
    cwd,
    encoding: "utf8",
    env: { ...process.env, NO_COLOR: "1" },
    stdio: ["ignore", "pipe", "inherit"],
  });

const freePort = (): Promise<number> =>
  new Promise((resolvePort, rejectPort) => {
    const probe = createServer();
    probe.on("error", rejectPort);
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address() as AddressInfo;
      probe.close(() => resolvePort(port));
    });
  });

const waitForHttp = async (url: string, editor: ChildProcess): Promise<void> => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (editor.exitCode !== null) {
      throw new Error(`The marimo editor exited with status ${editor.exitCode}.`);
    }
    const ready = await fetch(url, { signal: AbortSignal.timeout(5000) }).then(
      (response) => response.ok,
      () => false,
    );
    if (ready) {
      return;
    }
    await new Promise((wait) => setTimeout(wait, 500));
  }
  throw new Error(`${url} did not answer within ${timeoutMs / 1000} seconds.`);
};

const workspace = await mkdtemp(join(tmpdir(), "marimo-studio-figure-"));
const notebook = join(workspace, "quadratic_program.py");
const exportRoot = join(workspace, "exports");
// join() resolves ".." segments, so containment needs a path-segment boundary.
const isExported = (file: string): boolean => file.startsWith(`${exportRoot}${sep}`);
const server = createHttpServer((request, response) => {
  let path: string;
  try {
    path = decodeURIComponent(new URL(request.url ?? "/", "http://localhost").pathname);
  } catch {
    response.writeHead(400).end();
    return;
  }
  let file = join(exportRoot, path);
  if (isExported(file) && existsSync(file) && statSync(file).isDirectory()) {
    file = join(file, "index.html");
  }
  if (!isExported(file) || !existsSync(file)) {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, {
    "content-type": contentTypes[extname(file)] ?? "application/octet-stream",
  });
  createReadStream(file).pipe(response);
});
let editor: ChildProcess | undefined;
// The editor runs in its own process group, so one signal stops uvx, the
// marimo server, and its kernel.
const stopEditor = (): void => {
  if (editor?.pid !== undefined) {
    try {
      process.kill(-editor.pid, "SIGTERM");
    } catch {
      // The group already exited.
    }
  }
};
// `finally` blocks do not run when a signal ends the capture.
for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => {
    stopEditor();
    rmSync(workspace, { force: true, recursive: true });
    process.exit(130);
  });
}
const pageErrors: string[] = [];
const browser = await chromium.launch();

try {
  await copyFile(join(root, "examples/quadratic_program.py"), notebook);
  const viewRoot = join(workspace, "studio/quadratic_program");
  for (const { kind, source, view } of views) {
    await cp(source, join(viewRoot, view), { recursive: true });
    if (kind === "report") {
      await copyFile(typstLibrary, join(viewRoot, view, "marimo.typ"));
    }
  }
  // The copied notebook names the example's own default view, which the
  // scratch workspace leaves out.
  run("uv", [
    "run",
    "--frozen",
    "marimo-studio",
    "view",
    "default",
    views[0]?.view ?? "",
    "--target",
    notebook,
  ]);
  for (const { view } of views) {
    console.log(`exporting ${view}`);
    run("uv", [
      "run",
      "--frozen",
      "marimo-studio",
      "view",
      "export",
      view,
      "--target",
      notebook,
      "--output",
      join(exportRoot, view),
      "--runtime",
      "zero-python",
      "--json",
    ]);
  }

  // The notebook capture runs marimo without Studio, at the version Studio is
  // developed against. marimo reads .marimo.toml from the working directory
  // first, so the editor ignores the user's own settings.
  const marimoVersion = run("uv", [
    "run",
    "--frozen",
    "python",
    "-c",
    "import marimo; print(marimo.__version__)",
  ]).trim();
  await writeFile(
    join(workspace, ".marimo.toml"),
    [
      "[display]",
      'theme = "light"',
      "code_editor_font_size = 14",
      'cell_output = "below"',
      "",
      "[runtime]",
      "auto_instantiate = true",
      "",
      "[completion]",
      "activate_on_typing = false",
      "copilot = false",
      "",
    ].join("\n"),
  );
  const editorPort = await freePort();
  editor = spawn(
    "uvx",
    [
      "--from",
      `marimo==${marimoVersion}`,
      "marimo",
      "edit",
      "quadratic_program.py",
      "--sandbox",
      "--headless",
      "--no-token",
      "--port",
      String(editorPort),
    ],
    // Its own process group lets cleanup stop the editor and its kernel.
    { cwd: workspace, detached: true, stdio: ["ignore", "ignore", "inherit"] },
  );
  const editorUrl = `http://127.0.0.1:${editorPort}/`;
  await waitForHttp(editorUrl, editor);

  await new Promise<void>((listening) => server.listen(0, "127.0.0.1", listening));
  const exportUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}/`;
  await mkdir(shotsDir, { recursive: true });

  const open = async (url: string, viewport: { height: number; width: number }): Promise<Page> => {
    const context = await browser.newContext({
      deviceScaleFactor: scale,
      reducedMotion: "reduce",
      viewport,
    });
    const page: Page = await context.newPage();
    page.on("pageerror", (error: Error) => pageErrors.push(`${url}: ${error.message}`));
    await page.goto(url, { timeout: timeoutMs, waitUntil: "load" });
    return page;
  };

  // The notebook is ready once every cell has run and a named cell shows its
  // figure.
  const notebookPage = await open(editorUrl, notebookViewport);
  await notebookPage.waitForFunction(
    (names: string[]) =>
      names.every((name) => document.querySelector(`.marimo-cell[data-cell-name="${name}"]`)) &&
      names.some((name) => document.querySelector(`.marimo-cell[data-cell-name="${name}"] img`)) &&
      document.querySelector('[data-status="running"], [data-status="queued"]') === null,
    cells,
    { polling: 250, timeout: timeoutMs },
  );
  await notebookPage.evaluate(() => document.fonts.ready.then(() => undefined));
  await notebookPage.waitForTimeout(settleMs);
  await notebookPage.mouse.move(0, 0);
  for (const name of cells) {
    const cell = notebookPage.locator(`.marimo-cell[data-cell-name="${name}"]`);
    await cell.scrollIntoViewIfNeeded();
    await notebookPage.waitForTimeout(300);
    await cell.screenshot({ path: join(shotsDir, `cell--${name}.png`) });
    console.log(`captured cell ${name}`);
  }
  // compose.html reads the notebook order to count the cells a figure skips.
  const order = await notebookPage.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>(".marimo-cell")].map(
      (cell) => cell.dataset.cellName ?? "",
    ),
  );
  await writeFile(join(shotsDir, "notebook.json"), `${JSON.stringify({ order }, null, 2)}\n`);
  await notebookPage.context().close();

  for (const { kind, view } of views) {
    const url = new URL(`${view}/`, exportUrl).href;
    if (kind === "page") {
      // A page is ready once every projection host shows its result.
      const page = await open(url, pageViewport);
      await page.waitForFunction(
        () =>
          [
            ...document.querySelectorAll<HTMLElement>("marimo-cell, marimo-output, [mo-value]"),
          ].every((host) => host.dataset.state === "ready"),
        undefined,
        { polling: 250, timeout: timeoutMs },
      );
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      await page.waitForTimeout(settleMs);
      await page.locator("#app-shell").screenshot({ path: join(shotsDir, `${view}.png`) });
      await page.context().close();
    } else {
      // The render host paints the PDF with pdf.js. The capture keeps the
      // painted page at its own resolution, without the host around it. The
      // host is ready once it shows the PDF rendered with notebook values,
      // which leaves its status empty. pdf.js fills the text layer after it
      // paints the canvas.
      const page = await open(url, reportViewport);
      await page.waitForFunction(
        () => {
          const viewer = document.querySelector<HTMLElement>("marimo-output[render]");
          const root = viewer?.shadowRoot;
          return (
            viewer?.dataset.state === "ready" &&
            root?.querySelector('[role="status"]')?.textContent === "" &&
            (root.querySelector(".page .textLayer")?.childElementCount ?? 0) > 0
          );
        },
        undefined,
        { polling: 250, timeout: timeoutMs },
      );
      await page.waitForTimeout(settleMs);
      const png = await page.evaluate(() => {
        const canvas = document
          .querySelector("marimo-output[render]")
          ?.shadowRoot?.querySelector(".page canvas");
        return canvas instanceof HTMLCanvasElement ? canvas.toDataURL("image/png") : "";
      });
      await writeFile(
        join(shotsDir, `${view}.png`),
        Buffer.from(png.split(",")[1] ?? "", "base64"),
      );
      await page.context().close();
    }
    console.log(`captured ${view}`);
  }
  if (pageErrors.length > 0) {
    throw new Error(`Captured pages reported errors:\n${pageErrors.join("\n")}`);
  }
} finally {
  await browser.close();
  server.close();
  stopEditor();
  if (editor && editor.exitCode === null && editor.signalCode === null) {
    await Promise.race([once(editor, "exit"), new Promise((wait) => setTimeout(wait, 10_000))]);
  }
  rmSync(workspace, { force: true, recursive: true });
}
