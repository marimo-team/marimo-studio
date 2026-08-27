import type { ObserveViewRequest } from "@marimo-studio/protocol/development-events";

import { afterEach, beforeEach, expect, it, vi } from "vite-plus/test";

import { ViewActivationAcknowledgementError } from "../src/app/activation-remote.ts";
import { WorkspaceEventCoordinator } from "../src/app/workspace-event-coordinator.ts";
import { deferred, EventSourceStub, setup } from "./workspace-event-test-support.ts";

beforeEach(() => {
  EventSourceStub.instances = [];
  vi.stubGlobal("EventSource", EventSourceStub);
});

afterEach(() => {
  vi.useRealTimers();
});

it("selects and then acknowledges an agent activation", async () => {
  const { acknowledge, coordinator, model, preview } = setup(["dashboard"]);
  model.replaceViews(["dashboard", "report"]);
  model.ensureAvailable.mockResolvedValue(true);

  EventSourceStub.instances[0]?.emit(
    "activate",
    JSON.stringify({ schema: 1, generation: 7, view: "report" }),
  );

  await vi.waitFor(() =>
    expect(acknowledge).toHaveBeenCalledWith(7, "report", expect.any(AbortSignal)),
  );
  expect(model.ensureAvailable).toHaveBeenCalledWith("report", expect.any(AbortSignal));
  expect(model.choose).toHaveBeenCalledWith(
    "report",
    "build",
    undefined,
    expect.any(AbortSignal),
    "agent",
  );
  expect(preview.reload).not.toHaveBeenCalled();
  coordinator.dispose();
});

it("refreshes an already active view before acknowledging its activation", async () => {
  const { acknowledge, coordinator, model, preview } = setup();

  EventSourceStub.instances[0]?.emit(
    "activate",
    JSON.stringify({ schema: 1, generation: 8, view: "dashboard" }),
  );

  await vi.waitFor(() =>
    expect(acknowledge).toHaveBeenCalledWith(8, "dashboard", expect.any(AbortSignal)),
  );
  expect(model.choose).toHaveBeenCalledWith(
    "dashboard",
    "build",
    undefined,
    expect.any(AbortSignal),
    "agent",
  );
  expect(preview.reload).toHaveBeenCalledOnce();
  expect(preview.reload.mock.invocationCallOrder[0]).toBeLessThan(
    acknowledge.mock.invocationCallOrder[0]!,
  );
  coordinator.dispose();
});

it("acknowledges host promotion without reloading the starting preview", async () => {
  const activation = { schema: 1, generation: 8, view: "dashboard" } as const;
  const { acknowledge, coordinator, preview } = setup(undefined, activation);

  await vi.waitFor(() =>
    expect(acknowledge).toHaveBeenCalledWith(8, "dashboard", expect.any(AbortSignal)),
  );
  EventSourceStub.instances[0]?.emit("activate", JSON.stringify(activation));
  await Promise.resolve();

  expect(acknowledge).toHaveBeenCalledOnce();
  expect(preview.reload).not.toHaveBeenCalled();
  coordinator.dispose();
});

it("retries a failed host-promotion acknowledgement after replay", async () => {
  const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  const activation = { schema: 1, generation: 8, view: "dashboard" } as const;
  const { acknowledge, coordinator } = setup(undefined, activation, true);
  await vi.waitFor(() => expect(EventSourceStub.instances).toHaveLength(2));

  EventSourceStub.instances[1]?.emit(
    "ready",
    JSON.stringify({ schema: 1, view: "dashboard", revision: "v2" }),
  );
  EventSourceStub.instances[1]?.emit("activate", JSON.stringify(activation));
  await vi.waitFor(() => expect(acknowledge).toHaveBeenCalledTimes(2));

  expect(EventSourceStub.instances).toHaveLength(2);
  warning.mockRestore();
  coordinator.dispose();
});

it("restores the previous view after terminal acknowledgement failure", async () => {
  const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  const { acknowledge, coordinator, model } = setup();
  acknowledge.mockRejectedValueOnce(
    new ViewActivationAcknowledgementError("rejected", "activation rejected"),
  );

  EventSourceStub.instances[0]?.emit(
    "activate",
    JSON.stringify({ schema: 1, generation: 9, view: "report" }),
  );

  await vi.waitFor(() => expect(model.choose).toHaveBeenCalledTimes(2));
  expect(model.views.getSnapshot().current).toBe("dashboard");
  expect(model.choose.mock.calls.map(([view]) => view)).toEqual(["report", "dashboard"]);
  expect(model.choose).toHaveBeenLastCalledWith(
    "dashboard",
    "preserve",
    undefined,
    expect.any(AbortSignal),
    "agent",
  );
  expect(acknowledge).toHaveBeenCalledOnce();
  warning.mockRestore();
  coordinator.dispose();
});

it("keeps the selected view while an acknowledgement outcome is uncertain", async () => {
  const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  const { acknowledge, coordinator, model } = setup();
  acknowledge.mockRejectedValueOnce(
    new ViewActivationAcknowledgementError("uncertain", "response body was lost"),
  );

  EventSourceStub.instances[0]?.emit(
    "activate",
    JSON.stringify({ schema: 1, generation: 9, view: "report" }),
  );

  await vi.waitFor(() => expect(EventSourceStub.instances).toHaveLength(2));
  expect(model.views.getSnapshot().current).toBe("report");
  expect(model.choose.mock.calls.map(([view]) => view)).toEqual(["report"]);
  expect(acknowledge).toHaveBeenCalledOnce();
  warning.mockRestore();
  coordinator.dispose();
});

it("releases a timed-out activation so the same generation can replay", async () => {
  vi.useFakeTimers();
  const { acknowledge, coordinator, model } = setup();
  const stalled = deferred<boolean>();
  model.ensureAvailable.mockReturnValueOnce(stalled.promise).mockResolvedValueOnce(true);
  const activation = { schema: 1, generation: 14, view: "report" } as const;
  const events = EventSourceStub.instances[0]!;

  events.emit("activate", JSON.stringify(activation));
  await vi.waitFor(() => expect(model.ensureAvailable).toHaveBeenCalledOnce());
  await vi.advanceTimersByTimeAsync(110_000);
  await Promise.resolve();
  await Promise.resolve();
  expect(acknowledge).not.toHaveBeenCalled();

  await vi.waitFor(() => expect(EventSourceStub.instances).toHaveLength(2));
  const replay = EventSourceStub.instances[1]!;
  replay.emit("ready", JSON.stringify({ schema: 1, view: "dashboard", revision: "revision-2" }));
  replay.emit("activate", JSON.stringify(activation));
  await vi.waitFor(() => expect(acknowledge).toHaveBeenCalledOnce());
  stalled.resolve(true);
  await Promise.resolve();

  expect(model.ensureAvailable).toHaveBeenCalledTimes(2);
  expect(model.choose).toHaveBeenCalledOnce();
  expect(model.views.getSnapshot().current).toBe("report");
  coordinator.dispose();
});

it("does not acknowledge a failed or malformed activation", async () => {
  const { acknowledge, coordinator, model } = setup();
  model.choose.mockResolvedValue(false);
  const events = EventSourceStub.instances[0];
  events?.emit("activate", JSON.stringify({ schema: 1, generation: 2, view: "report" }));
  events?.emit("activate", '{"schema":1,"view":""}');
  await Promise.resolve();

  expect(acknowledge).not.toHaveBeenCalled();
  coordinator.dispose();
});

it("lets the newest activation generation own selection and acknowledgement", async () => {
  const { acknowledge, coordinator, model } = setup(["dashboard", "report", "analysis"]);
  const report = deferred<boolean>();
  const analysis = deferred<boolean>();
  model.ensureAvailable.mockImplementation((view) => {
    if (view === "report") {
      return report.promise;
    }
    if (view === "analysis") {
      return analysis.promise;
    }
    return Promise.resolve(true);
  });
  const events = EventSourceStub.instances[0];
  events?.emit("activate", JSON.stringify({ schema: 1, generation: 10, view: "report" }));
  events?.emit("activate", JSON.stringify({ schema: 1, generation: 11, view: "analysis" }));

  analysis.resolve(true);
  await vi.waitFor(() =>
    expect(acknowledge).toHaveBeenCalledWith(11, "analysis", expect.any(AbortSignal)),
  );
  report.resolve(true);
  await Promise.resolve();
  await Promise.resolve();

  expect(model.choose).toHaveBeenCalledTimes(1);
  expect(model.choose).toHaveBeenCalledWith(
    "analysis",
    "build",
    undefined,
    expect.any(AbortSignal),
    "agent",
  );
  expect(model.views.getSnapshot().current).toBe("analysis");
  expect(acknowledge).toHaveBeenCalledOnce();
  coordinator.dispose();
});

it("cancels an older selection before a newer unavailable activation settles", async () => {
  let current = "dashboard";
  let selectionGeneration = 0;
  const reportSelection = deferred<boolean>();
  const analysisInventory = deferred<boolean>();
  const choose = vi.fn(async (view: string) => {
    const generation = ++selectionGeneration;
    const selected = view === "report" ? await reportSelection.promise : true;
    if (!selected || generation !== selectionGeneration) {
      return false;
    }
    current = view;
    return true;
  });
  const cancelPendingSelection = vi.fn(() => {
    selectionGeneration += 1;
  });
  const acknowledge = vi.fn(async () => undefined);
  const coordinator = new WorkspaceEventCoordinator({
    eventsUrl: "/events?file=notebook.py",
    views: {
      subscribe: () => () => undefined,
      getSnapshot: () => ({ current }),
      refreshInventory: async () => undefined,
      ensureAvailable: async (view) =>
        view === "analysis" ? await analysisInventory.promise : true,
      choose,
      cancelPendingSelection,
    },
    preview: {
      requestObservation: vi.fn(),
      editorSessionChanged: vi.fn(),
      reload: vi.fn(),
      presentationBaseline: vi.fn(),
      presentationBuildStarted: vi.fn(),
      presentationBuildCompleted: vi.fn(),
      presentationStreamAbandoned: vi.fn(),
      presentationChanged: vi.fn(),
    },
    source: { reconcile: vi.fn(), externalChanges: vi.fn() },
    acknowledge,
  });
  coordinator.start();
  const events = EventSourceStub.instances[0];
  events?.emit("activate", JSON.stringify({ schema: 1, generation: 20, view: "report" }));
  await vi.waitFor(() =>
    expect(choose).toHaveBeenCalledWith(
      "report",
      "build",
      undefined,
      expect.any(AbortSignal),
      "agent",
    ),
  );

  events?.emit("activate", JSON.stringify({ schema: 1, generation: 21, view: "analysis" }));
  reportSelection.resolve(true);
  analysisInventory.resolve(false);
  await Promise.resolve();
  await Promise.resolve();

  expect(cancelPendingSelection).toHaveBeenCalledTimes(2);
  expect(current).toBe("dashboard");
  expect(acknowledge).not.toHaveBeenCalled();
  coordinator.dispose();
});

it("ignores observations that are not bound to an active view generation", async () => {
  const { coordinator, model, preview } = setup();
  const request: ObserveViewRequest = {
    schema: 1,
    requestId: "request-report",
    view: "report",
    runtime: "server",
    runtimeInstance: "runtime-instance",
    revision: "revision-report",
  };

  EventSourceStub.instances[0]?.emit("observe", JSON.stringify(request));

  await Promise.resolve();

  expect(preview.requestObservation).not.toHaveBeenCalled();
  expect(model.choose).not.toHaveBeenCalled();
  coordinator.dispose();
});

it("forwards focused observations only while their view is active", async () => {
  const { coordinator, model, preview } = setup();
  const request: ObserveViewRequest = {
    schema: 1,
    requestId: "request-dashboard",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "runtime-instance",
    revision: "revision-dashboard",
    activeViewGeneration: 4,
  };
  const events = EventSourceStub.instances[0];

  events?.emit("observe", JSON.stringify(request));
  await vi.waitFor(() => expect(preview.requestObservation).toHaveBeenCalledWith(request));
  events?.emit(
    "observe",
    JSON.stringify({ ...request, requestId: "request-report", view: "report" }),
  );
  await Promise.resolve();

  expect(preview.requestObservation).toHaveBeenCalledOnce();
  expect(model.choose).not.toHaveBeenCalled();
  coordinator.dispose();
});

it("forwards validated session replacement evidence", () => {
  const { coordinator, preview } = setup();
  const binding = {
    schema: 1,
    generation: 2,
    sessionId: "s_reconnected",
    replaced: true,
  } as const;
  const events = EventSourceStub.instances[0];
  events?.emit("session", JSON.stringify(binding));
  events?.emit("session", JSON.stringify({ ...binding, generation: 0 }));

  expect(preview.editorSessionChanged).toHaveBeenCalledOnce();
  expect(preview.editorSessionChanged).toHaveBeenCalledWith(binding);
  coordinator.dispose();
});

it("aborts pending acknowledgement and blocks events after disposal", async () => {
  let signal: AbortSignal | undefined;
  const { acknowledge, coordinator, model } = setup();
  acknowledge.mockImplementation(async (_generation, _view, activeSignal) => {
    signal = activeSignal;
    await new Promise<void>(() => {});
  });
  EventSourceStub.instances[0]?.emit(
    "activate",
    JSON.stringify({ schema: 1, generation: 9, view: "report" }),
  );
  await vi.waitFor(() => expect(acknowledge).toHaveBeenCalledOnce());

  const events = EventSourceStub.instances.at(-1);
  coordinator.dispose();
  events?.emit("change");

  expect(signal?.aborted).toBe(true);
  expect(events?.closed).toBe(true);
  expect(model.refreshInventory).not.toHaveBeenCalled();
});
