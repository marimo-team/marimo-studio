import type { Page } from "@playwright/test";

import { readFile, readdir, rm, stat } from "node:fs/promises";
import { createServer, type Server } from "node:http";
import { dirname, extname, resolve, sep } from "node:path";
import { z } from "zod";

import {
  editorSlider,
  editorFrame,
  expect,
  exportWorkspaceViewDefault,
  exportWorkspaceView,
  preparedStudioEntryUrl,
  pureHtmlPath,
  test,
  waitForPreview,
  workspacePreparedNotebookPath,
  workspaceRootPath,
} from "./fixture.ts";

const contentTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".ttf", "font/ttf"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
]);
const listeningAddressSchema = z.object({ port: z.int().positive() });

const serveDirectory = async (root: string) => {
  const canonicalRoot = resolve(root);
  const server: Server = createServer(async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", "http://127.0.0.1");
      const decoded = decodeURIComponent(url.pathname).replace(/^\/+/, "");
      const relative = decoded === "" || decoded.endsWith("/") ? `${decoded}index.html` : decoded;
      const candidate = resolve(canonicalRoot, relative);
      if (candidate !== canonicalRoot && !candidate.startsWith(`${canonicalRoot}${sep}`)) {
        response.writeHead(404).end();
        return;
      }
      const details = await stat(candidate);
      if (!details.isFile()) {
        response.writeHead(404).end();
        return;
      }
      const body = await readFile(candidate);
      response.writeHead(200, {
        "Content-Length": String(body.byteLength),
        "Content-Type": contentTypes.get(extname(candidate)) ?? "application/octet-stream",
      });
      response.end(request.method === "HEAD" ? undefined : body);
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise<void>((resolveReady, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolveReady();
    });
  });
  const address = listeningAddressSchema.parse(server.address());
  return {
    origin: `http://127.0.0.1:${address.port}`,
    close: () =>
      new Promise<void>((resolveClose, reject) =>
        server.close((error) => (error ? reject(error) : resolveClose())),
      ),
  };
};

const openPreparedPreview = async (page: Page) => {
  await page.goto(preparedStudioEntryUrl);
  return {
    editor: editorFrame(page),
    prepared: await waitForPreview(page, "zero-python"),
  };
};

test("recovers a zero-Python preview after its control revision expires", async ({
  browserDiagnostics,
  page,
}) => {
  test.setTimeout(240_000);
  let serverControlReads = 0;
  let forcedRevisionRecovery = false;
  await page.route("**/_marimo-studio/views/prepared/controls?**", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("runtime") !== "server") {
      await route.continue();
      return;
    }
    serverControlReads += 1;
    if (serverControlReads !== 2) {
      await route.continue();
      return;
    }
    forcedRevisionRecovery = true;
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        error: "presentation-revision-unavailable",
        message: "Forced stale control revision",
        transient: true,
      }),
    });
  });
  const { prepared } = await openPreparedPreview(page);
  await expect.poll(() => forcedRevisionRecovery).toBe(true);
  await expect.poll(() => serverControlReads).toBeGreaterThanOrEqual(3);
  await expect(prepared.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
  await expect
    .poll(
      () =>
        browserDiagnostics.messages.filter(
          (message) =>
            message.includes("http 409:") && message.includes("Forced stale control revision"),
        ).length,
    )
    .toBe(1);
  const forcedDiagnostic = browserDiagnostics.messages.findIndex(
    (message) => message.includes("http 409:") && message.includes("Forced stale control revision"),
  );
  expect(forcedDiagnostic).toBeGreaterThanOrEqual(0);
  browserDiagnostics.messages.splice(forcedDiagnostic, 1);
});

test("names prepared controls and exposes pointer targets", async ({ page }) => {
  test.setTimeout(240_000);
  const { prepared } = await openPreparedPreview(page);
  const scaleHost = prepared.locator("#prepared-scale-output");
  const scale = scaleHost.getByRole("slider", { name: "Prepared scale" });
  const region = prepared
    .locator('marimo-cell[name="filters_control"]')
    .getByRole("combobox", { name: "Region" });

  await expect(scaleHost).toHaveAttribute("aria-label", "Prepared scale");
  await expect(scaleHost).toHaveAttribute("role", "group");
  await expect(scale).toHaveAttribute("aria-label", "Prepared scale");
  expect(await scale.getAttribute("aria-label")).not.toContain("<");
  const scaleBox = await scale.boundingBox();
  expect(scaleBox?.width).toBeGreaterThanOrEqual(44);
  expect(scaleBox?.height).toBeGreaterThanOrEqual(44);
  const regionBox = await region.boundingBox();
  expect(regionBox?.height).toBeGreaterThanOrEqual(44);
});

test("selects prepared states and synchronizes their controls", async ({ page }) => {
  test.setTimeout(240_000);
  const { editor, prepared } = await openPreparedPreview(page);
  const editorRegion = editor.getByRole("combobox", { name: "Region" });
  await expect(editorRegion).toContainText("Europe");
  const scale = editorSlider(page);
  const preparedScale = prepared.locator('marimo-cell[name="controls"]').getByRole("slider");

  await expect(prepared.locator("#prepared-metric")).toHaveText("42");
  await expect(preparedScale).toHaveAttribute("aria-valuenow", "2");
  await preparedScale.press("Home");
  await expect(preparedScale).toHaveAttribute("aria-valuenow", "2");
  await expect(prepared.locator("#prepared-metric")).toHaveText("42");
  await scale.press("Home");
  await expect(prepared.locator("#prepared-metric")).toHaveText("21", { timeout: 30_000 });
  await scale.press("End");
  await expect(prepared.locator("#prepared-metric")).toHaveText("63", { timeout: 30_000 });

  await expect(prepared.locator("#prepared-summary").locator("h3")).toHaveText("Current total: 63");
  await expect(preparedScale).toHaveAttribute("aria-valuenow", "3");
  await expect(prepared.locator('marimo-cell[name="metric"]')).toContainText("prepared metric: 63");

  const stateInventory = await prepared
    .locator("html")
    .evaluate(() => globalThis.marimoStudio.state?.states().map((state) => state.inputs.scale));
  expect(stateInventory).toEqual(expect.arrayContaining([1, 2, 3]));

  await prepared.locator("html").evaluate(async () => {
    await globalThis.marimoStudio.state?.update({ scale: 1 });
  });
  await expect(prepared.locator("#prepared-metric")).toHaveText("21");
  await prepared.locator("html").evaluate(async () => {
    await Promise.allSettled([
      globalThis.marimoStudio.state?.update({ scale: 1 }),
      globalThis.marimoStudio.state?.update({ scale: 3 }),
    ]);
  });
  await expect(prepared.locator("#prepared-metric")).toHaveText("63");

  const missingRejected = await prepared.locator("html").evaluate(async () => {
    try {
      await globalThis.marimoStudio.state?.update({ scale: 99 });
      return false;
    } catch {
      return true;
    }
  });
  expect(missingRejected).toBe(true);
  await expect(prepared.locator("#prepared-metric")).toHaveText("63");

  await preparedScale.press("Home");
  await expect(prepared.locator("#prepared-metric")).toHaveText("21");
  await preparedScale.press("End");
  await expect(prepared.locator("#prepared-metric")).toHaveText("63");
  await expect(scale).toHaveAttribute("aria-valuenow", "3", { timeout: 30_000 });

  const filterCell = prepared.locator('marimo-cell[name="filters_control"]');
  const filterOutput = prepared.locator("#prepared-filter-output");
  const cellRegion = filterCell.getByRole("combobox", { name: "Region" });
  const outputRegion = filterOutput.getByRole("combobox", { name: "Region" });
  const editorDetail = editor.getByTestId("marimo-plugin-text-input");
  const cellDetail = filterCell.getByTestId("marimo-plugin-text-input");
  const outputDetail = filterOutput.getByTestId("marimo-plugin-text-input");
  await expect(prepared.locator("#prepared-region")).toHaveText("unsubmitted");
  await editor.getByRole("button", { name: "Apply filters" }).click();
  await expect(prepared.locator("#prepared-region")).toHaveText("emea", { timeout: 45_000 });

  await expect(editorDetail).toHaveValue("ready", { timeout: 30_000 });
  await expect(cellDetail).toHaveValue("ready", { timeout: 30_000 });
  await expect(outputDetail).toHaveValue("ready", { timeout: 30_000 });
  await editorDetail.fill("from editor");
  await editorDetail.press("Enter");
  await expect(cellDetail).toHaveValue("from editor");
  await expect(outputDetail).toHaveValue("from editor");
  await cellDetail.fill("from prepared");
  await cellDetail.press("Enter");
  await expect(editorDetail).toHaveValue("from prepared");
  await expect(outputDetail).toHaveValue("from prepared");

  await editorRegion.selectOption({ label: "Asia Pacific" });
  await expect(cellRegion).toContainText("Asia Pacific");
  await expect(outputRegion).toContainText("Asia Pacific");
  await expect(prepared.locator("#prepared-region")).toHaveText("emea");

  await cellRegion.selectOption({ label: "Europe" });
  await expect(editorRegion).toContainText("Europe");
  await expect(outputRegion).toContainText("Europe");
  await expect(prepared.locator("#prepared-region")).toHaveText("emea");

  await cellRegion.selectOption({ label: "Asia Pacific" });
  await filterCell.getByRole("button", { name: "Apply filters" }).click();
  await expect(cellRegion).toContainText("Europe");
  await expect(cellDetail).toHaveValue("ready");
  await expect(prepared.locator("#prepared-region")).toHaveText("apac", { timeout: 45_000 });
  await expect(cellRegion).toContainText("Asia Pacific");
  await expect(outputRegion).toContainText("Asia Pacific");
  await expect(cellDetail).toHaveValue("from prepared");
  await expect(outputDetail).toHaveValue("from prepared");

  await scale.press("Home");
  await expect(prepared.locator("#prepared-metric")).toHaveText("21", { timeout: 30_000 });
  await scale.press("End");
  await expect(prepared.locator("#prepared-metric")).toHaveText("63", { timeout: 30_000 });

  const widget = prepared.getByRole("button", { name: /Widget count:/ });
  await expect(widget).toHaveText("Widget count: 7");
  await widget.click();
  await expect(widget).toHaveText("Widget count: 8");
});

test("serves the explicit baseline from the deployed zero-Python site", async ({ page }) => {
  test.setTimeout(240_000);
  const output = resolve(workspaceRootPath, "deployed", "prepared");
  await rm(output, { recursive: true, force: true });
  const exported = await exportWorkspaceView("prepared", output, workspacePreparedNotebookPath);
  expect(exported.runtime).toBe("zero-python");
  expect(resolve(exported.output)).toBe(output);
  const files = await readdir(output, { recursive: true });
  expect(files.some((file) => /(?:notebook\.py|pyodide|websocket|worker)/iu.test(file))).toBe(
    false,
  );

  const staticServer = await serveDirectory(workspaceRootPath);
  const deployed = await page.context().newPage();
  const requests: string[] = [];
  const responses: Array<{ readonly status: number; readonly url: string }> = [];
  const sockets: string[] = [];
  const errors: string[] = [];
  deployed.on("request", (request) => requests.push(request.url()));
  deployed.on("response", (response) =>
    responses.push({ status: response.status(), url: response.url() }),
  );
  deployed.on("websocket", (socket) => sockets.push(socket.url()));
  deployed.on("pageerror", (error) => errors.push(error.message));
  deployed.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  try {
    await deployed.goto(`${staticServer.origin}/deployed/prepared/?scale=99`);
    await expect(deployed.locator('script[type="module"][src$="zero-python.js"]')).toHaveCount(1);
    await expect(deployed.locator('script[type="module"][src$="runtime.js"]')).toHaveCount(0);
    await expect
      .poll(() =>
        deployed.evaluate(async () => {
          if (!globalThis.marimoStudio) return false;
          return Promise.race([
            globalThis.marimoStudio.ready().then(() => true),
            new Promise<false>((resolveReady) => setTimeout(() => resolveReady(false), 250)),
          ]);
        }),
      )
      .toBe(true);
    const deployedStateInventory = await deployed.evaluate(() =>
      globalThis.marimoStudio.state?.states().map((state) => state.inputs.scale),
    );
    expect(deployedStateInventory).toEqual([2]);
    await expect
      .poll(() => deployed.evaluate(() => globalThis.marimoStudio.state?.inputs().scale))
      .toBe(2);
    await expect(deployed.locator("#prepared-metric")).toHaveText("42");
    await deployed.evaluate(() => globalThis.history.pushState({}, "", "?scale=3"));
    await expect(deployed.locator("#prepared-metric")).toHaveText("42");
    await expect(deployed.locator("#prepared-summary").locator("h3")).toHaveText(
      "Current total: 42",
    );
    const undeclaredStateRejected = await deployed.evaluate(async () => {
      try {
        await globalThis.marimoStudio.state?.update({ scale: 1 });
        return false;
      } catch {
        return true;
      }
    });
    expect(undeclaredStateRejected).toBe(true);
    await expect(deployed.locator("#prepared-metric")).toHaveText("42");
    const deployedWidget = deployed.getByRole("button", { name: /Widget count:/ });
    await expect(deployedWidget).toHaveText("Widget count: 7");
    await deployedWidget.click();
    await expect(deployedWidget).toHaveText("Widget count: 8");

    await deployed.setViewportSize({ width: 360, height: 800 });
    expect(
      await deployed.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);

    expect(sockets).toEqual([]);
    expect(
      requests.filter((url) =>
        /(?:\/api(?:\/|$)|\/ws(?:\/|$)|\/sse(?:\/|$)|pyodide|\.whl(?:\?|$)|notebook\.py)/iu.test(
          new URL(url).pathname,
        ),
      ),
    ).toEqual([]);
    expect(requests.some((url) => new URL(url).pathname.endsWith("/index.json"))).toBe(true);
    expect(
      responses
        .filter(
          ({ url }) =>
            new URL(url).pathname === "/deployed/prepared/_marimo-studio/assets/zero-python.js",
        )
        .map(({ status }) => status),
    ).toEqual([200]);
    expect(responses.filter(({ status }) => status < 200 || status >= 300)).toEqual([]);
    expect(errors).toEqual([]);
  } finally {
    await deployed.close();
    await staticServer.close();
  }
});

test("exports a projection-free view as its authored static files", async ({ page }) => {
  const output = resolve(workspaceRootPath, "deployed", "pure");
  await rm(output, { recursive: true, force: true });
  const exported = await exportWorkspaceViewDefault("pure", output, workspacePreparedNotebookPath);
  expect(exported.runtime).toBe("zero-python");
  expect(resolve(exported.output)).toBe(output);

  const authoredRoot = dirname(pureHtmlPath);
  expect(await readFile(resolve(output, "index.html"))).toEqual(await readFile(pureHtmlPath));
  expect(await readFile(resolve(output, "app.css"))).toEqual(
    await readFile(resolve(authoredRoot, "app.css")),
  );
  expect(await readFile(resolve(output, "pure.js"))).toEqual(
    await readFile(resolve(authoredRoot, "pure.js")),
  );
  expect(await readFile(resolve(output, "public/report.txt"))).toEqual(
    await readFile(resolve(workspaceRootPath, "public/report.txt")),
  );
  const files = await readdir(output, { recursive: true });
  expect(
    files.filter((file) =>
      /(?:_marimo-studio|manifest|publication|runtime\.(?:css|js))/iu.test(file),
    ),
  ).toEqual([]);

  const staticServer = await serveDirectory(workspaceRootPath);
  const requests: string[] = [];
  const responses: Array<{ readonly status: number; readonly url: string }> = [];
  const sockets: string[] = [];
  const errors: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("response", (response) =>
    responses.push({ status: response.status(), url: response.url() }),
  );
  page.on("websocket", (socket) => sockets.push(socket.url()));
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  try {
    await page.goto(`${staticServer.origin}/deployed/pure/`);
    await expect(page.getByRole("heading", { name: "Pure static fixture" })).toBeVisible();
    await expect(page.locator("#pure-status")).toHaveText("Authored script ready");
    expect(
      await page.evaluate(async () => await fetch("./public/report.txt").then((r) => r.text())),
    ).toBe("Pure static report\n");
    await expect(page.locator("[data-marimo-studio-runtime]")).toHaveCount(0);
    await expect(page.locator('script[src*="runtime"]')).toHaveCount(0);
    await expect(page.locator('link[href*="runtime"]')).toHaveCount(0);
    expect(await page.evaluate(() => globalThis.marimoStudio)).toBeUndefined();

    expect(sockets).toEqual([]);
    expect(requests.map((url) => new URL(url).pathname).sort()).toEqual(
      [
        "/deployed/pure/",
        "/deployed/pure/app.css",
        "/deployed/pure/public/report.txt",
        "/deployed/pure/pure.js",
      ].sort(),
    );
    expect(responses.filter(({ status }) => status < 200 || status >= 300)).toEqual([]);
    expect(errors).toEqual([]);
  } finally {
    await staticServer.close();
  }
});
