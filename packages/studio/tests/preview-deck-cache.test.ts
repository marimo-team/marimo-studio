import { afterEach, expect, it, vi } from "vite-plus/test";

import { PreviewControlController } from "../src/features/preview/control-controller.ts";
import { PREVIEW_VIEW_CACHE_SIZE, PreviewDeck } from "../src/features/preview/deck.ts";
import { ViewController } from "../src/features/views/controller.ts";
import { starter, viewList } from "./fixtures.ts";
import { createFrameBridgeSource, installFrameBridge } from "./frame-bridge-test-support.ts";
import {
  cachedFrames,
  dispatchPreviewMessage,
  dispatchPreviewRefreshHandshake,
  frame,
} from "./preview-test-support.ts";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

it("releases inactive runtime frames before deleting the previous view", async () => {
  const editor = frame("complete");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const serverWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
  const wasmWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
  Object.defineProperty(serverFrame, "contentWindow", {
    configurable: true,
    value: serverWindow,
  });
  Object.defineProperty(wasmFrame, "contentWindow", {
    configurable: true,
    value: wasmWindow,
  });
  const viewUrl = vi.fn((view: string, runtime: string) => `/${view}?runtime=${runtime}`);
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "", hash: "" },
    runtimes: ["server", "wasm"],
    viewUrl,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  const frames = cachedFrames(deck, { server: serverFrame, wasm: wasmFrame });
  const windows = new Map(
    [...frames].map(([id, cached]) => {
      let frameWindow = {
        dispatchEvent: vi.fn(),
        postMessage: vi.fn(),
      };
      if (id === "server") {
        frameWindow = serverWindow;
      } else if (id === "wasm") {
        frameWindow = wasmWindow;
      }
      Object.defineProperty(cached, "contentWindow", { configurable: true, value: frameWindow });
      return [id, frameWindow];
    }),
  );
  deck.attach(editor, frames);
  deck.switchRuntime("wasm");
  deck.switchRuntime("server");
  for (const [runtime, source] of [
    ["server", serverWindow],
    ["wasm", wasmWindow],
  ] as const) {
    dispatchPreviewMessage(source, {
      type: "marimo-studio:receiver-ready",
      runtime,
      lifecycleId: deck.getSnapshot().states[runtime]!.lifecycleId,
      view: "dashboard",
      revision: "revision-1",
    });
  }

  const staged = deck.stageView("report");
  const report = deck
    .getSnapshot()
    .frames.find((item) => item.runtime === "server" && item.view === "report");
  expect(report).toBeDefined();
  const reportWindow = windows.get(report!.id)!;
  const reportLifecycleId = deck.getSnapshot().states.server!.lifecycleId;
  dispatchPreviewMessage(reportWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    view: "report",
    lifecycleId: reportLifecycleId,
    revision: "revision-2",
  });
  dispatchPreviewMessage(reportWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    view: "report",
    lifecycleId: reportLifecycleId,
    revision: "revision-2",
    sessionId: "s_123456",
  });
  await expect(staged.ready).resolves.toBe(true);
  const prepared = deck.prepareViewDeletion("report");

  expect(await prepared).toBe(true);
  expect(wasmFrame.src).toBe("about:blank");
  deck.switchRuntime("wasm");
  expect(viewUrl).toHaveBeenLastCalledWith("report", "wasm", {
    query: "",
    hash: "",
  });
  deck.dispose();
});

it("clears presentation state before a removed view name is recreated", async () => {
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "", hash: "" },
    runtimes: ["server"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  const frames = cachedFrames(deck, {});
  const windows = new Map(
    [...frames].map(([id, cached]) => {
      const frameWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
      Object.defineProperty(cached, "contentWindow", { configurable: true, value: frameWindow });
      return [id, frameWindow];
    }),
  );
  deck.attach(frame("complete"), frames);
  const makeReady = async (view: string, revision: string, refresh = false) => {
    const staged = deck.stageView(view);
    const selected = deck
      .getSnapshot()
      .frames.find((item) => item.runtime === "server" && item.view === view)!;
    const frameWindow = windows.get(selected.id)!;
    const lifecycleId = deck.getSnapshot().states.server!.lifecycleId;
    dispatchPreviewMessage(frameWindow, {
      type: "marimo-studio:receiver-ready",
      runtime: "server",
      view,
      lifecycleId,
      revision,
    });
    if (refresh) {
      dispatchPreviewRefreshHandshake(frameWindow, {
        runtime: "server",
        view,
        lifecycleId,
        revision,
      });
    }
    dispatchPreviewMessage(frameWindow, {
      type: "marimo-studio:view-ready",
      runtime: "server",
      view,
      lifecycleId,
      revision,
    });
    await expect(staged.ready).resolves.toBe(true);
    return { frame: frames.get(selected.id)!, frameWindow };
  };

  const report = await makeReady("report", "revision:report:old");
  deck.presentationBaseline("report", "revision:report:old");
  deck.presentationBuildStarted("report");
  await makeReady("dashboard", "revision:dashboard", true);
  deck.releaseView("report");
  expect(report.frame.src).toBe("about:blank");
  windows.forEach((frameWindow) => frameWindow.postMessage.mockClear());

  const recreated = deck.stageView("report");
  const selected = deck
    .getSnapshot()
    .frames.find((item) => item.runtime === "server" && item.view === "report")!;
  const frameWindow = windows.get(selected.id)!;
  const lifecycleId = deck.getSnapshot().states.server!.lifecycleId;
  expect(frameWindow.postMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:presentation-refresh", phase: "pending" }),
    "*",
  );
  dispatchPreviewMessage(frameWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    view: "report",
    lifecycleId,
    revision: "revision:report:new",
  });
  dispatchPreviewMessage(frameWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    view: "report",
    lifecycleId,
    revision: "revision:report:new",
  });

  await expect(recreated.ready).resolves.toBe(true);
  expect(frameWindow.postMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:presentation-change" }),
    "*",
  );
  deck.dispose();
});

it("keeps the prior document warm after creation and evicts it at the cache bound", async () => {
  const editor = frame("complete");
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "", hash: "" },
    runtimes: ["server"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  const frames = cachedFrames(deck, {});
  const windows = new Map(
    [...frames].map(([id, cached]) => {
      const frameWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
      Object.defineProperty(cached, "contentWindow", { configurable: true, value: frameWindow });
      return [id, frameWindow];
    }),
  );
  deck.attach(editor, frames);
  let dashboardLifecycleId = 0;

  const makeReady = async (view: string) => {
    const staged = deck.stageView(view);
    const selected = deck
      .getSnapshot()
      .frames.find((item) => item.runtime === "server" && item.view === view);
    expect(selected).toBeDefined();
    const frameWindow = windows.get(selected!.id)!;
    const lifecycleId = deck.getSnapshot().states.server!.lifecycleId;
    if (view === "dashboard" && lifecycleId === dashboardLifecycleId) {
      dispatchPreviewRefreshHandshake(frameWindow, {
        runtime: "server",
        view,
        lifecycleId,
        revision: `revision:${view}`,
      });
    } else {
      dispatchPreviewMessage(frameWindow, {
        type: "marimo-studio:receiver-ready",
        runtime: "server",
        view,
        lifecycleId,
        revision: `revision:${view}`,
      });
    }
    dispatchPreviewMessage(frameWindow, {
      type: "marimo-studio:view-ready",
      runtime: "server",
      view,
      lifecycleId,
      revision: `revision:${view}`,
    });
    await expect(staged.ready).resolves.toBe(true);
    return { selected, frame: frames.get(selected!.id)!, frameWindow };
  };

  const dashboardSlot = deck.getSnapshot().frames.find(({ view }) => view === "dashboard")!;
  const dashboardFrame = frames.get(dashboardSlot.id)!;
  const dashboardWindow = windows.get(dashboardSlot.id)!;
  dashboardLifecycleId = deck.getSnapshot().states.server!.lifecycleId;
  dispatchPreviewMessage(dashboardWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    view: "dashboard",
    lifecycleId: dashboardLifecycleId,
    revision: "revision:dashboard",
  });
  dispatchPreviewMessage(dashboardWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    view: "dashboard",
    lifecycleId: dashboardLifecycleId,
    revision: "revision:dashboard",
  });
  const dashboardSource = dashboardFrame.src;

  const controller = new ViewController(
    "dashboard",
    ["dashboard"],
    {
      list: vi.fn(async () => viewList(["dashboard", "report"])),
      create: vi.fn(async (name: string, _starter: string) => ({
        schema: 2 as const,
        name,
        provider: "marimo-studio/vanilla",
        studio_url: `/studio/${name}/`,
        view_url: `/${name}/`,
      })),
      remove: vi.fn(),
    },
    async (view) => {
      await makeReady(view);
      return true;
    },
    vi.fn(async () => true),
    vi.fn(),
    [starter],
    starter.id,
    vi.fn(async () => true),
    (view) => deck.releaseView(view),
  );

  await expect(controller.create("report", starter.id)).resolves.toBe(true);
  await expect(controller.choose("dashboard")).resolves.toBe(true);
  expect(deck.getSnapshot().states.server!.lifecycleId).toBe(dashboardLifecycleId);
  expect(
    deck
      .getSnapshot()
      .frames.find(({ runtime, view }) => runtime === "server" && view === "dashboard")?.id,
  ).toBe(dashboardSlot.id);
  expect(frames.get(dashboardSlot.id)).toBe(dashboardFrame);
  expect(dashboardFrame.contentWindow).toBe(dashboardWindow);
  expect(dashboardFrame.src).toBe(dashboardSource);

  await makeReady("gallery");
  const story = await makeReady("story");
  await makeReady("analysis");
  const assigned = deck
    .getSnapshot()
    .frames.filter(({ runtime, view }) => runtime === "server" && view);
  expect(assigned).toHaveLength(PREVIEW_VIEW_CACHE_SIZE);
  expect(assigned.map(({ view }) => view)).not.toContain("dashboard");
  expect(assigned.map(({ view }) => view)).not.toContain("report");
  expect(story.frame.src).toContain("/story");
  controller.dispose();
  deck.dispose();
});

it("supersedes an abandoned build before refreshing a cached sibling", async () => {
  const beginControls = vi.spyOn(PreviewControlController.prototype, "begin");
  const editor = frame("complete");
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "", hash: "" },
    runtimes: ["server"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  const frames = cachedFrames(deck, {});
  const windows = new Map(
    [...frames].map(([id, cached]) => {
      const frameWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
      Object.defineProperty(cached, "contentWindow", { configurable: true, value: frameWindow });
      return [id, frameWindow];
    }),
  );
  deck.attach(editor, frames);
  const makeReady = async (view: string, refresh = false) => {
    const staged = deck.stageView(view);
    const selected = deck
      .getSnapshot()
      .frames.find((item) => item.runtime === "server" && item.view === view)!;
    const frameWindow = windows.get(selected.id)!;
    const lifecycleId = deck.getSnapshot().states.server!.lifecycleId;
    dispatchPreviewMessage(frameWindow, {
      type: "marimo-studio:receiver-ready",
      runtime: "server",
      view,
      lifecycleId,
      revision: `revision:${view}`,
    });
    if (refresh) {
      dispatchPreviewRefreshHandshake(frameWindow, {
        runtime: "server",
        view,
        lifecycleId,
        revision: `revision:${view}`,
      });
    }
    dispatchPreviewMessage(frameWindow, {
      type: "marimo-studio:view-ready",
      runtime: "server",
      view,
      lifecycleId,
      revision: `revision:${view}`,
    });
    await expect(staged.ready).resolves.toBe(true);
    return { frame: frames.get(selected.id)!, frameWindow, lifecycleId };
  };

  const report = await makeReady("report");
  deck.presentationBaseline("report", "revision:report");
  deck.presentationBuildStarted("report");
  await makeReady("dashboard", true);
  deck.presentationStreamAbandoned("report");
  expect(report.frameWindow.postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:presentation-refresh",
      runtime: "server",
      lifecycleId: report.lifecycleId,
      view: "report",
      phase: "settled",
    },
    "*",
  );
  const cachedSource = report.frame.src;
  report.frameWindow.postMessage.mockClear();
  beginControls.mockClear();
  const revisiting = deck.stageView("report");
  let settled = false;
  void revisiting.ready.then(() => {
    settled = true;
  });
  await Promise.resolve();

  const nextLifecycleId = deck.getSnapshot().states.server!.lifecycleId;
  expect(settled).toBe(false);
  expect(nextLifecycleId).toBe(report.lifecycleId);
  expect(report.frame.src).toBe(cachedSource);
  expect(beginControls).not.toHaveBeenCalled();
  expect(report.frameWindow.postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:presentation-change",
      runtime: "server",
      lifecycleId: report.lifecycleId,
      view: "report",
    },
    "*",
  );
  dispatchPreviewRefreshHandshake(report.frameWindow, {
    runtime: "server",
    view: "report",
    lifecycleId: nextLifecycleId,
    revision: "revision:report",
  });
  dispatchPreviewMessage(report.frameWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    view: "report",
    lifecycleId: nextLifecycleId,
    revision: "revision:report",
  });
  await expect(revisiting.ready).resolves.toBe(true);
  expect(beginControls).toHaveBeenCalled();
  expect(report.frame.src).toBe(cachedSource);
  deck.dispose();
});

it("keeps document identity monotonic when an inactive controller is recreated", async () => {
  const editor = frame("complete");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const serverWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
  const wasmWindow = createFrameBridgeSource();
  Object.defineProperty(serverFrame, "contentWindow", {
    configurable: true,
    value: serverWindow,
  });
  Object.defineProperty(wasmFrame, "contentWindow", {
    configurable: true,
    value: wasmWindow,
  });
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "", hash: "" },
    runtimes: ["server", "wasm"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  deck.attach(
    editor,
    new Map([
      ["server", serverFrame],
      ["wasm", wasmFrame],
    ]),
  );
  deck.switchRuntime("wasm");
  deck.switchRuntime("server");
  for (const [runtime, source] of [
    ["server", serverWindow],
    ["wasm", wasmWindow],
  ] as const) {
    dispatchPreviewMessage(source, {
      type: "marimo-studio:receiver-ready",
      runtime,
      lifecycleId: deck.getSnapshot().states[runtime]!.lifecycleId,
      view: "dashboard",
      revision: "revision-1",
    });
  }

  void deck.stageView("report").ready;
  const previousLifecycleId = deck.getSnapshot().states.wasm!.lifecycleId;
  void deck.prepareViewDeletion("report");
  const recreatedLifecycleId = deck.getSnapshot().states.wasm!.lifecycleId;
  installFrameBridge(wasmFrame, wasmWindow, {
    lifecycleId: recreatedLifecycleId,
    revision: "revision:current",
    runtime: "wasm",
    sessionId: null,
    view: "report",
  });
  expect(recreatedLifecycleId).toBeGreaterThan(previousLifecycleId);
  deck.switchRuntime("wasm");
  dispatchPreviewMessage(wasmWindow, {
    type: "marimo-studio:view-ready",
    runtime: "wasm",
    lifecycleId: previousLifecycleId,
    view: "report",
    revision: "revision:stale",
  });
  expect(deck.runtimeDiagnostics("wasm")?.current.phase).toBe("connecting");
  dispatchPreviewMessage(wasmWindow, {
    type: "marimo-studio:view-ready",
    runtime: "wasm",
    lifecycleId: recreatedLifecycleId,
    view: "report",
    revision: "revision:current",
  });
  await vi.waitFor(() =>
    expect(deck.runtimeDiagnostics("wasm")).toMatchObject({
      revision: "revision:current",
      current: { phase: "ready" },
    }),
  );
  deck.dispose();
});
