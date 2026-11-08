import "./framed-document.ts";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { runtimeConfig } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "http://localhost:3000/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
};

const disposers: (() => void)[] = [];

afterEach(() => {
  disposers.splice(0).forEach((dispose) => dispose());
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

// The watcher captures the document base and readiness is a module singleton,
// so each test loads a fresh module graph.
const readyView = async () => {
  vi.resetModules();
  const [{ watchViewScriptErrors }, observer, { renderedViewDiagnostics }, config] =
    await Promise.all([
      import("../src/document/view-script-errors.ts"),
      import("../src/rendered-view-observer.ts"),
      import("../src/rendered-view-state.ts"),
      import("../src/runtime-config/index.ts"),
    ]);
  vi.spyOn(globalThis.parent, "postMessage").mockImplementation(() => undefined);
  config.commitRuntimeConfig(runtimeConfig());
  const stopWatching = watchViewScriptErrors();
  observer.startRenderedViewObserver(async () => {});
  observer.setRuntimeConnectionState("ready");
  disposers.push(stopWatching, observer.stopRenderedViewObserver);
  expect(pageState()).toBe("ready");
  return { observer, renderedViewDiagnostics, stopWatching };
};

const pageState = () => document.documentElement.dataset.marimoStudioState;

const viewFile = (path: string) => new URL(path, document.baseURI).href;

const throwFrom = (filename: string, error: Error | null = new TypeError("rows is undefined")) =>
  globalThis.dispatchEvent(new ErrorEvent("error", { filename, lineno: 12, colno: 4, error }));

test("an uncaught error in a view script fails the page with its location", async () => {
  const { renderedViewDiagnostics } = await readyView();

  throwFrom(viewFile("assets/index.js"));

  expect(pageState()).toBe("error");
  const notice = document.querySelector("[data-marimo-studio-diagnostic]")?.textContent;
  expect(notice).toContain("assets/index.js:12:4");
  expect(notice).toContain("rows is undefined");
  expect(renderedViewDiagnostics()).toContainEqual(
    expect.objectContaining({ code: "view-script-error", scope: "presentation" }),
  );
});

test("an inline module script error names the inline script", async () => {
  await readyView();

  throwFrom(document.URL);

  expect(document.querySelector("[data-marimo-studio-diagnostic]")?.textContent).toContain(
    "inline script:12:4",
  );
});

test("an unhandled rejection from a view script fails the page", async () => {
  await readyView();
  const reason = new Error("fetch failed");
  reason.stack = `Error: fetch failed\n    at load (${viewFile("assets/index.js")}:40:7)`;

  globalThis.dispatchEvent(
    new PromiseRejectionEvent("unhandledrejection", { promise: Promise.resolve(), reason }),
  );

  const notice = document.querySelector("[data-marimo-studio-diagnostic]")?.textContent;
  expect(notice).toContain("assets/index.js:40:7");
  expect(notice).toContain("fetch failed");
});

test("a view script failure outlives observer restarts and watcher disposal", async () => {
  const { observer, stopWatching } = await readyView();
  throwFrom(viewFile("main.js"));

  stopWatching();
  observer.stopRenderedViewObserver();
  observer.startRenderedViewObserver(async () => {});
  observer.setRuntimeConnectionState("ready");

  expect(pageState()).toBe("error");
});

test("browser warnings and code outside the view files leave the page ready", async () => {
  await readyView();

  throwFrom(document.URL, null);
  throwFrom("", null);
  throwFrom("https://cdn.example.com/widget.js");
  throwFrom(viewFile("_marimo-studio/assets/runtime.js"));
  throwFrom(viewFile("@file/widget.js"));

  expect(pageState()).toBe("ready");
});

test("worker failures from before startup and after it warn without failing the view", async () => {
  globalThis.__MARIMO_STUDIO_WORKER_ERRORS__ = [
    { url: viewFile("assets/map.worker.js"), message: "Uncaught TypeError: rows is undefined" },
    { url: "blob:null/1234", message: "" },
  ];
  const { renderedViewDiagnostics } = await readyView();

  globalThis.__MARIMO_STUDIO_WORKER_ERRORS__?.push({
    url: viewFile("assets/late.worker.js"),
    message: `Failed to load ${viewFile("assets/late.worker.js")} after http://other.test/token/x.js`,
  });

  const warnings = renderedViewDiagnostics().filter(
    (diagnostic) => diagnostic.code === "view-worker-error",
  );
  expect(warnings.map(({ severity, message }) => [severity, message])).toEqual([
    ["warning", "worker assets/map.worker.js: Uncaught TypeError: rows is undefined"],
    ["warning", "inline worker: failed to start"],
    [
      "warning",
      "worker assets/late.worker.js: Failed to load assets/late.worker.js after (worker URL)",
    ],
  ]);
  expect(pageState()).toBe("ready");
});

test("a crash before observers start shows as an error once they start", async () => {
  vi.resetModules();
  const [{ watchViewScriptErrors }, observer, config] = await Promise.all([
    import("../src/document/view-script-errors.ts"),
    import("../src/rendered-view-observer.ts"),
    import("../src/runtime-config/index.ts"),
  ]);
  vi.spyOn(globalThis.parent, "postMessage").mockImplementation(() => undefined);
  config.commitRuntimeConfig(runtimeConfig());
  disposers.push(watchViewScriptErrors(), observer.stopRenderedViewObserver);

  throwFrom(viewFile("assets/index.js"));
  observer.startRenderedViewObserver(async () => {});

  expect(pageState()).toBe("error");
});
