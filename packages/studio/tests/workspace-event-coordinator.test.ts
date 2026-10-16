import { afterEach, beforeEach, expect, it, vi } from "vite-plus/test";

import { deferred, WebSocketStub, setup } from "./workspace-event-test-support.ts";

beforeEach(() => {
  WebSocketStub.instances = [];
  vi.stubGlobal("WebSocket", WebSocketStub);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("reconnects the workspace stream after a committed view selection", async () => {
  const { coordinator, model } = setup();
  expect(WebSocketStub.instances).toHaveLength(1);
  expect(WebSocketStub.instances[0]?.url).toContain("marimo_studio_view=dashboard");
  const firstGeneration = Number(
    new URL(WebSocketStub.instances[0]!.url).searchParams.get("marimo_studio_connection"),
  );

  await model.views.choose("report", "preserve");

  expect(WebSocketStub.instances).toHaveLength(2);
  expect(WebSocketStub.instances[0]?.closed).toBe(false);
  expect(WebSocketStub.instances[1]?.url).toContain("marimo_studio_view=report");
  const replacementGeneration = Number(
    new URL(WebSocketStub.instances[1]!.url).searchParams.get("marimo_studio_connection"),
  );
  expect(replacementGeneration).toBeGreaterThan(firstGeneration);
  WebSocketStub.instances[1]?.emit(
    "ready",
    JSON.stringify({ schema: 1, view: "report", revision: "presentation-v2" }),
  );
  expect(WebSocketStub.instances[0]?.closed).toBe(true);
  coordinator.dispose();
});

it("keeps the committed stream authoritative while a view is still preparing", async () => {
  const { coordinator, model } = setup();
  const selection = deferred<boolean>();
  model.deferNextSelection(selection.promise);

  const choosing = model.views.choose("report", "preserve");
  await vi.waitFor(() => expect(model.views.getSnapshot().selecting).toBe("report"));

  expect(model.views.getSnapshot().current).toBe("dashboard");
  expect(WebSocketStub.instances).toHaveLength(1);
  expect(WebSocketStub.instances[0]?.url).toContain("marimo_studio_view=dashboard");

  selection.resolve(true);
  expect(await choosing).toBe(true);
  expect(WebSocketStub.instances).toHaveLength(2);
  expect(WebSocketStub.instances[1]?.url).toContain("marimo_studio_view=report");
  coordinator.dispose();
});

it("keeps agent acknowledgement behind target preparation and committed stream ownership", async () => {
  const { acknowledge, coordinator, model, preview } = setup();
  const selection = deferred<boolean>();
  model.deferNextSelection(selection.promise);

  WebSocketStub.instances[0]?.emit(
    "activate",
    JSON.stringify({ schema: 1, generation: 7, view: "report" }),
  );
  await vi.waitFor(() => expect(model.views.getSnapshot().selecting).toBe("report"));

  expect(model.views.getSnapshot().current).toBe("dashboard");
  expect(acknowledge).not.toHaveBeenCalled();
  expect(WebSocketStub.instances).toHaveLength(1);
  expect(WebSocketStub.instances[0]?.url).toContain("marimo_studio_view=dashboard");

  selection.resolve(true);
  await vi.waitFor(() =>
    expect(acknowledge).toHaveBeenCalledWith(
      { schema: 1, generation: 7, view: "report" },
      expect.objectContaining({ previewUrl: "http://localhost/preview/" }),
      expect.any(AbortSignal),
    ),
  );
  expect(model.views.getSnapshot().current).toBe("report");
  expect(preview.presentationStreamAbandoned).toHaveBeenCalledWith("dashboard");
  expect(WebSocketStub.instances).toHaveLength(2);
  expect(WebSocketStub.instances[1]?.url).toContain("marimo_studio_view=report");
  coordinator.dispose();
});

it("keeps the committed stream after a prepared view is rejected", async () => {
  const { coordinator, model } = setup();
  const selection = deferred<boolean>();
  model.deferNextSelection(selection.promise);

  const choosing = model.views.choose("report", "preserve");
  await vi.waitFor(() => expect(model.views.getSnapshot().selecting).toBe("report"));
  selection.resolve(false);

  expect(await choosing).toBe(false);
  expect(model.views.getSnapshot()).toMatchObject({ current: "dashboard", selecting: undefined });
  expect(WebSocketStub.instances).toHaveLength(1);
  expect(WebSocketStub.instances[0]?.url).toContain("marimo_studio_view=dashboard");
  coordinator.dispose();
});

it("retains the current stream until a slow replacement is ready", async () => {
  const { coordinator, model, preview } = setup();
  const current = WebSocketStub.instances[0]!;
  current.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "v1" }));

  await model.views.choose("report", "preserve");
  const replacement = WebSocketStub.instances[1]!;

  expect(current.closed).toBe(false);
  current.emit(
    "session",
    JSON.stringify({ schema: 1, generation: 2, sessionId: "stale", replaced: false }),
  );
  expect(preview.editorSessionChanged).not.toHaveBeenCalled();

  replacement.emit("ready", JSON.stringify({ schema: 1, view: "report", revision: "v2" }));

  expect(current.closed).toBe(true);
  expect(replacement.closed).toBe(false);
  expect(preview.presentationBaseline).toHaveBeenLastCalledWith("report", "v2");
  coordinator.dispose();
});

it("recovers the committed view through a higher-generation ready stream", async () => {
  const { coordinator } = setup();
  const current = WebSocketStub.instances[0]!;
  current.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "v1" }));
  const owner = new AbortController();
  let recovered = false;

  const recovery = coordinator.recoverActiveView("dashboard", owner.signal).then(() => {
    recovered = true;
  });

  expect(current.closed).toBe(true);
  expect(WebSocketStub.instances).toHaveLength(2);
  const replacement = WebSocketStub.instances[1]!;
  expect(replacement.url).toContain("marimo_studio_view=dashboard");
  expect(recovered).toBe(false);

  replacement.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "v1" }));
  await recovery;

  expect(recovered).toBe(true);
  coordinator.dispose();
});

it("bounds a committed-view recovery that never becomes ready", async () => {
  vi.useFakeTimers();
  const { coordinator } = setup();
  const recovery = coordinator.recoverActiveView("dashboard", new AbortController().signal);
  const rejected = expect(recovery).rejects.toMatchObject({ name: "TimeoutError" });

  await Promise.resolve();
  expect(WebSocketStub.instances).toHaveLength(2);
  await vi.runAllTimersAsync();

  await rejected;
  coordinator.dispose();
});

it("routes project, build, presentation, and view events to their owners", async () => {
  const { coordinator, model, preview, source } = setup();
  WebSocketStub.instances[0]?.emit(
    "ready",
    JSON.stringify({ schema: 1, view: "dashboard", revision: "presentation-v1" }),
  );
  WebSocketStub.instances[0]?.emit(
    "change",
    JSON.stringify({
      kind: "project",
      files: [{ path: "src/app.css", revision: "sha256:next" }],
    }),
  );
  WebSocketStub.instances[0]?.emit(
    "change",
    JSON.stringify({ kind: "build", phase: "building", files: [] }),
  );
  WebSocketStub.instances[0]?.emit(
    "change",
    JSON.stringify({
      kind: "build",
      build: { phase: "published", diagnostics: [] },
      revision: "presentation-v2",
      files: [],
    }),
  );
  WebSocketStub.instances[0]?.emit(
    "change",
    JSON.stringify({
      kind: "presentation",
      view: "dashboard",
      revision: "presentation-v2",
      files: [],
    }),
  );
  WebSocketStub.instances[0]?.emit("change", JSON.stringify({ kind: "views", files: [] }));

  await vi.waitFor(() => expect(model.refreshInventory).toHaveBeenCalledTimes(2));
  expect(source.reconcile).toHaveBeenCalledTimes(4);
  expect(preview.presentationBaseline).toHaveBeenCalledWith("dashboard", "presentation-v1");
  expect(preview.presentationBuildStarted).toHaveBeenCalledWith("dashboard");
  expect(preview.presentationBuildCompleted).toHaveBeenCalledWith("dashboard", "presentation-v2");
  expect(preview.presentationChanged).toHaveBeenCalledWith("dashboard", "presentation-v2");
  expect(source.externalChanges).toHaveBeenCalledWith([
    { path: "src/app.css", revision: "sha256:next" },
  ]);
  coordinator.dispose();
});

it("fences mutation reconciliation across ready baselines and view changes", async () => {
  const { coordinator, model, preview } = setup();
  WebSocketStub.instances[0]?.emit(
    "ready",
    JSON.stringify({ schema: 1, view: "dashboard", revision: "presentation-v1" }),
  );

  coordinator.reconcileNotebookMutation(7);
  const reconciliation = WebSocketStub.instances[1];
  expect(preview.presentationBuildStarted).toHaveBeenLastCalledWith("dashboard");
  reconciliation?.emit(
    "ready",
    JSON.stringify({ schema: 1, view: "dashboard", revision: "presentation-v1" }),
  );
  reconciliation?.emit(
    "change",
    JSON.stringify({
      kind: "build",
      build: { phase: "published", diagnostics: [] },
      revision: "presentation-v1",
      files: [],
    }),
  );
  expect(preview.presentationBuildCompleted).toHaveBeenLastCalledWith(
    "dashboard",
    "presentation-v1",
    7,
  );

  coordinator.reconcileNotebookMutation(8);
  await model.views.choose("report", "preserve");
  const switched = WebSocketStub.instances.at(-1);
  expect(preview.presentationBuildStarted).toHaveBeenLastCalledWith("report");
  switched?.emit(
    "ready",
    JSON.stringify({ schema: 1, view: "report", revision: "presentation-report" }),
  );
  switched?.emit(
    "change",
    JSON.stringify({
      kind: "build",
      build: { phase: "published", diagnostics: [] },
      revision: "presentation-report",
      files: [],
    }),
  );
  expect(preview.presentationBuildCompleted).toHaveBeenLastCalledWith(
    "report",
    "presentation-report",
    8,
  );
  coordinator.dispose();
});

it("consumes a stream mutation tag after its first completed build", () => {
  const { coordinator, preview } = setup();
  coordinator.reconcileNotebookMutation(7);
  const stream = WebSocketStub.instances[1]!;
  stream.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "v1" }));
  preview.presentationBuildStarted.mockClear();
  preview.presentationBuildCompleted.mockClear();

  stream.emit(
    "change",
    JSON.stringify({ kind: "build", phase: "building", revision: null, files: [] }),
  );
  stream.emit(
    "change",
    JSON.stringify({
      kind: "build",
      build: { phase: "published", diagnostics: [] },
      revision: "v1",
      files: [],
    }),
  );

  expect(preview.presentationBuildStarted).toHaveBeenLastCalledWith("dashboard");
  expect(preview.presentationBuildCompleted).toHaveBeenLastCalledWith("dashboard", "v1", 7);
  preview.presentationBuildStarted.mockClear();
  preview.presentationBuildCompleted.mockClear();

  stream.emit(
    "change",
    JSON.stringify({ kind: "build", phase: "building", revision: null, files: [] }),
  );
  stream.emit(
    "change",
    JSON.stringify({
      kind: "build",
      build: { phase: "published", diagnostics: [] },
      revision: "v2",
      files: [],
    }),
  );

  expect(preview.presentationBuildStarted).toHaveBeenCalledWith("dashboard");
  expect(preview.presentationBuildCompleted).toHaveBeenCalledWith("dashboard", "v2");
  coordinator.dispose();
});

it("replaces a tagged mutation stream with an ordinary editor-reload reconciliation", () => {
  const { coordinator, preview } = setup();
  const original = WebSocketStub.instances[0]!;
  original.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "v1" }));
  coordinator.reconcileNotebookMutation(7);
  const tagged = WebSocketStub.instances[1]!;
  preview.presentationBaseline.mockClear();
  preview.presentationBuildCompleted.mockClear();

  coordinator.reconcileEditorReload();

  const replacement = WebSocketStub.instances[2]!;
  expect(tagged.closed).toBe(true);
  expect(original.closed).toBe(false);
  expect(preview.presentationBuildStarted).toHaveBeenLastCalledWith("dashboard");

  tagged.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "stale" }));
  tagged.emit(
    "change",
    JSON.stringify({
      kind: "build",
      build: { phase: "published", diagnostics: [] },
      revision: "stale",
      files: [],
    }),
  );
  expect(preview.presentationBaseline).not.toHaveBeenCalled();
  expect(preview.presentationBuildCompleted).not.toHaveBeenCalled();

  replacement.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "repaired" }));
  replacement.emit(
    "change",
    JSON.stringify({
      kind: "build",
      build: { phase: "published", diagnostics: [] },
      revision: "repaired",
      files: [],
    }),
  );

  expect(original.closed).toBe(true);
  expect(preview.presentationBaseline).toHaveBeenCalledWith("dashboard", "repaired");
  expect(preview.presentationBuildCompleted).toHaveBeenCalledWith("dashboard", "repaired");
  coordinator.dispose();
});

it("refreshes inventory before reconciling a selected manifest generation", async () => {
  const { coordinator, model, source } = setup();
  const events = WebSocketStub.instances[0];

  events?.emit("change", JSON.stringify({ kind: "views", files: [] }));
  events?.emit("change", JSON.stringify({ kind: "project", files: [] }));

  await vi.waitFor(() => expect(model.refreshInventory).toHaveBeenCalledOnce());
  expect(source.externalChanges).toHaveBeenCalledWith([]);
  expect(model.refreshInventory.mock.invocationCallOrder[0]).toBeLessThan(
    source.externalChanges.mock.invocationCallOrder[0]!,
  );
  coordinator.dispose();
});

it("ignores callbacks from a replaced stream", async () => {
  const { coordinator, model } = setup();
  const stale = WebSocketStub.instances[0];
  await model.views.choose("report", "preserve");

  stale?.emit("change");
  await Promise.resolve();

  expect(model.refreshInventory).not.toHaveBeenCalled();
  coordinator.dispose();
});

const closedStream = () => {
  vi.useFakeTimers();
  return setup();
};

it("replaces a closed event socket and resumes its events", async () => {
  const { coordinator, source } = closedStream();
  const closed = WebSocketStub.instances[0]!;
  closed.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "v1" }));

  closed.fail();
  expect(WebSocketStub.instances).toHaveLength(1);
  await vi.advanceTimersByTimeAsync(1_000);

  expect(WebSocketStub.instances).toHaveLength(2);
  const replacement = WebSocketStub.instances[1]!;
  expect(replacement.url).toContain("marimo_studio_view=dashboard");
  replacement.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "v2" }));
  replacement.emit(
    "change",
    JSON.stringify({ kind: "project", files: [{ path: "index.html", revision: "sha256:next" }] }),
  );
  expect(source.externalChanges).toHaveBeenCalledWith([
    { path: "index.html", revision: "sha256:next" },
  ]);
  coordinator.dispose();
});

it("backs off while a replacement stream keeps closing", async () => {
  const { coordinator } = closedStream();

  WebSocketStub.instances[0]!.fail();
  await vi.advanceTimersByTimeAsync(1_000);
  WebSocketStub.instances[1]!.fail();
  await vi.advanceTimersByTimeAsync(1_000);
  expect(WebSocketStub.instances).toHaveLength(2);
  await vi.advanceTimersByTimeAsync(1_000);
  expect(WebSocketStub.instances).toHaveLength(3);

  coordinator.dispose();
  WebSocketStub.instances[2]!.fail();
  await vi.advanceTimersByTimeAsync(60_000);
  expect(WebSocketStub.instances).toHaveLength(3);
});

it("reports a server restart and stops reconnecting to the earlier process", async () => {
  const { coordinator, preview } = closedStream();

  WebSocketStub.instances[0]!.fail(4204);
  await vi.advanceTimersByTimeAsync(60_000);

  expect(preview.serverRestarted).toHaveBeenCalledOnce();
  expect(WebSocketStub.instances).toHaveLength(1);
  coordinator.dispose();
});

it("closes a connecting event socket once its handshake completes", () => {
  const { coordinator } = setup();
  const connecting = WebSocketStub.instances[0]!;
  Object.assign(connecting, { readyState: 0 });

  coordinator.dispose();
  expect(connecting.closed).toBe(false);

  connecting.dispatchEvent(new Event("open"));
  expect(connecting.closed).toBe(true);
});

it("forwards build source locations to the presentation diagnostic", () => {
  const { coordinator, preview } = setup();
  const stream = WebSocketStub.instances[0]!;
  stream.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "v1" }));
  const source = { path: "src/App.tsx", line: 12, column: 4 };
  stream.emit(
    "change",
    JSON.stringify({
      kind: "build",
      phase: "complete",
      revision: "v1",
      build: {
        phase: "failed",
        diagnostics: [
          {
            severity: "error",
            code: "invalid-source",
            message: "Parse failed",
            hint: "Fix the source.",
            source,
          },
        ],
      },
      files: [],
    }),
  );
  expect(preview.presentationBuildCompleted).toHaveBeenLastCalledWith(
    "dashboard",
    "v1",
    undefined,
    expect.objectContaining({ source }),
  );
  coordinator.dispose();
});
