import { afterEach, beforeEach, expect, it, vi } from "vite-plus/test";

import { deferred, EventSourceStub, setup } from "./workspace-event-test-support.ts";

beforeEach(() => {
  EventSourceStub.instances = [];
  vi.stubGlobal("EventSource", EventSourceStub);
});

afterEach(() => {
  vi.useRealTimers();
});

it("reconnects the workspace stream after a committed view selection", async () => {
  const { coordinator, model } = setup();
  expect(EventSourceStub.instances).toHaveLength(1);
  expect(EventSourceStub.instances[0]?.url).toContain("marimo_studio_view=dashboard");
  const firstGeneration = Number(
    new URL(EventSourceStub.instances[0]!.url).searchParams.get("marimo_studio_connection"),
  );

  await model.views.choose("report", "preserve");

  expect(EventSourceStub.instances).toHaveLength(2);
  expect(EventSourceStub.instances[0]?.closed).toBe(false);
  expect(EventSourceStub.instances[1]?.url).toContain("marimo_studio_view=report");
  const replacementGeneration = Number(
    new URL(EventSourceStub.instances[1]!.url).searchParams.get("marimo_studio_connection"),
  );
  expect(replacementGeneration).toBeGreaterThan(firstGeneration);
  EventSourceStub.instances[1]?.emit(
    "ready",
    JSON.stringify({ schema: 1, view: "report", revision: "presentation-v2" }),
  );
  expect(EventSourceStub.instances[0]?.closed).toBe(true);
  coordinator.dispose();
});

it("keeps the committed stream authoritative while a view is still preparing", async () => {
  const { coordinator, model } = setup();
  const selection = deferred<boolean>();
  model.deferNextSelection(selection.promise);

  const choosing = model.views.choose("report", "preserve");
  await vi.waitFor(() => expect(model.views.getSnapshot().selecting).toBe("report"));

  expect(model.views.getSnapshot().current).toBe("dashboard");
  expect(EventSourceStub.instances).toHaveLength(1);
  expect(EventSourceStub.instances[0]?.url).toContain("marimo_studio_view=dashboard");

  selection.resolve(true);
  expect(await choosing).toBe(true);
  expect(EventSourceStub.instances).toHaveLength(2);
  expect(EventSourceStub.instances[1]?.url).toContain("marimo_studio_view=report");
  coordinator.dispose();
});

it("keeps agent acknowledgement behind target preparation and committed stream ownership", async () => {
  const { acknowledge, coordinator, model, preview } = setup();
  const selection = deferred<boolean>();
  model.deferNextSelection(selection.promise);

  EventSourceStub.instances[0]?.emit(
    "activate",
    JSON.stringify({ schema: 1, generation: 7, view: "report" }),
  );
  await vi.waitFor(() => expect(model.views.getSnapshot().selecting).toBe("report"));

  expect(model.views.getSnapshot().current).toBe("dashboard");
  expect(acknowledge).not.toHaveBeenCalled();
  expect(EventSourceStub.instances).toHaveLength(1);
  expect(EventSourceStub.instances[0]?.url).toContain("marimo_studio_view=dashboard");

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
  expect(EventSourceStub.instances).toHaveLength(2);
  expect(EventSourceStub.instances[1]?.url).toContain("marimo_studio_view=report");
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
  expect(EventSourceStub.instances).toHaveLength(1);
  expect(EventSourceStub.instances[0]?.url).toContain("marimo_studio_view=dashboard");
  coordinator.dispose();
});

it("retains the current stream until a slow replacement is ready", async () => {
  const { coordinator, model, preview } = setup();
  const current = EventSourceStub.instances[0]!;
  current.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "v1" }));

  await model.views.choose("report", "preserve");
  const replacement = EventSourceStub.instances[1]!;

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
  const current = EventSourceStub.instances[0]!;
  current.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "v1" }));
  const owner = new AbortController();
  let recovered = false;

  const recovery = coordinator.recoverActiveView("dashboard", owner.signal).then(() => {
    recovered = true;
  });

  expect(current.closed).toBe(true);
  expect(EventSourceStub.instances).toHaveLength(2);
  const replacement = EventSourceStub.instances[1]!;
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
  expect(EventSourceStub.instances).toHaveLength(2);
  await vi.runAllTimersAsync();

  await rejected;
  coordinator.dispose();
});

it("routes project, build, presentation, and view events to their owners", async () => {
  const { coordinator, model, preview, source } = setup();
  EventSourceStub.instances[0]?.emit(
    "ready",
    JSON.stringify({ schema: 1, view: "dashboard", revision: "presentation-v1" }),
  );
  EventSourceStub.instances[0]?.emit(
    "change",
    JSON.stringify({
      kind: "project",
      files: [{ path: "src/app.css", revision: "sha256:next" }],
    }),
  );
  EventSourceStub.instances[0]?.emit(
    "change",
    JSON.stringify({ kind: "build", phase: "building", files: [] }),
  );
  EventSourceStub.instances[0]?.emit(
    "change",
    JSON.stringify({
      kind: "build",
      build: { phase: "published", diagnostics: [] },
      revision: "presentation-v2",
      files: [],
    }),
  );
  EventSourceStub.instances[0]?.emit(
    "change",
    JSON.stringify({
      kind: "presentation",
      view: "dashboard",
      revision: "presentation-v2",
      files: [],
    }),
  );
  EventSourceStub.instances[0]?.emit("change", JSON.stringify({ kind: "views", files: [] }));

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
  EventSourceStub.instances[0]?.emit(
    "ready",
    JSON.stringify({ schema: 1, view: "dashboard", revision: "presentation-v1" }),
  );

  coordinator.reconcileNotebookMutation(7);
  const reconciliation = EventSourceStub.instances[1];
  expect(preview.presentationBuildStarted).toHaveBeenLastCalledWith("dashboard", 7);
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
  const switched = EventSourceStub.instances.at(-1);
  expect(preview.presentationBuildStarted).toHaveBeenLastCalledWith("report", 8);
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
  const stream = EventSourceStub.instances[1]!;
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

  expect(preview.presentationBuildStarted).toHaveBeenLastCalledWith("dashboard", 7);
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
  const original = EventSourceStub.instances[0]!;
  original.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "v1" }));
  coordinator.reconcileNotebookMutation(7);
  const tagged = EventSourceStub.instances[1]!;
  preview.presentationBaseline.mockClear();
  preview.presentationBuildCompleted.mockClear();

  coordinator.reconcileEditorReload();

  const replacement = EventSourceStub.instances[2]!;
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
  const events = EventSourceStub.instances[0];

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
  const stale = EventSourceStub.instances[0];
  await model.views.choose("report", "preserve");

  stale?.emit("change");
  await Promise.resolve();

  expect(model.refreshInventory).not.toHaveBeenCalled();
  coordinator.dispose();
});
