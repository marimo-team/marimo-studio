import { resolve } from "node:path";

import { e2eNetwork } from "../scripts/network.ts";
import { staticExportDirectory, workspaceDirectory } from "../scripts/paths.ts";
import {
  expect,
  retireWorkspacePage,
  test,
  waitForViewPreview,
  type BrowserDiagnostics,
} from "./fixture.ts";

const notebook = resolve(workspaceDirectory, "workers.py");
const staticOutput = resolve(staticExportDirectory, "workers");

declare global {
  var workerResults: Promise<object>;
}

test.use({ services: ["studio", "static"] });

// Browsers surface a worker's uncaught error as a page error, and a classic
// worker's failure inside importScripts carries the browser's load message.
const expectFixtureWorkerFailure = (diagnostics: BrowserDiagnostics) =>
  diagnostics.expectConsole({
    type: "pageerror",
    text: /fixture worker failure|importScripts|CORS-cross-origin/,
  });

test("starts URL and inline workers in a sandboxed Server view", async ({
  browserDiagnostics,
  page,
}) => {
  const workerFailure = expectFixtureWorkerFailure(browserDiagnostics);
  // WebKit reports the editor's unused font preloads on slow starts.
  const fontPreloads = browserDiagnostics.expectConsole({
    text: /was preloaded using link preload/,
    count: 20,
    required: false,
  });
  await page.goto("/studio/workers/?file=workers.py");
  const preview = await waitForViewPreview(page, "workers", "server", 120_000);
  const root = preview.locator("html");

  const results = await root.evaluate(() => globalThis.workerResults);

  expect(results).toMatchObject({
    origin: "null",
    classic: {
      name: "classic-worker",
      location: expect.stringMatching(/^http.*\/src\/workers\/classic\.js$/),
      chunk: "classic chunk",
      fetched: true,
      instance: true,
    },
    module: {
      name: "module-worker",
      location: expect.stringMatching(/^http.*\/src\/workers\/module\.js$/),
      chunk: "module chunk",
      importMeta: expect.stringMatching(/^http.*\/src\/workers\/module\.js$/),
      earlyMessage: "sent at construction",
      fetched: true,
      instance: true,
    },
    inlineModule: {
      name: "inline-module-worker",
      source: "inline",
      pageBlob: "page blob",
      instance: true,
    },
    largeInlineModule: { name: "large-inline-module-worker", source: "inline", instance: true },
    inlineClassic: { name: "inline-classic-worker", source: "inline", instance: true },
    failing: { failed: true },
    subclass: { name: "", instance: true },
    credentialed: { fetched: true, instance: true },
    crossOrigin: true,
  });

  await expect
    .poll(() => root.evaluate(() => globalThis.marimoStudio.diagnostics()))
    .toContainEqual(
      expect.objectContaining({
        code: "view-worker-error",
        severity: "warning",
        message: expect.stringContaining("workers/failing.js"),
      }),
    );
  await expect(root).toHaveAttribute("data-marimo-studio-state", "ready");
  workerFailure.recovered();
  fontPreloads.recovered();
  await retireWorkspacePage(page, browserDiagnostics);
});

test("static exports keep the browser's own workers", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  const workerFailure = expectFixtureWorkerFailure(browserDiagnostics);
  await studioCli.buildWorkspaceView("workers", notebook);
  await studioCli.exportWorkspaceView("workers", notebook, staticOutput);

  await page.goto(`${e2eNetwork.main.exported.origin}/workers/src/index.html`);
  const results = await page.evaluate(() => globalThis.workerResults);

  expect(results).toMatchObject({
    origin: e2eNetwork.main.exported.origin,
    classic: {
      location: `${e2eNetwork.main.exported.origin}/workers/src/workers/classic.js`,
      fetched: true,
    },
    module: {
      location: `${e2eNetwork.main.exported.origin}/workers/src/workers/module.js`,
      fetched: true,
    },
  });
  workerFailure.recovered();
});
