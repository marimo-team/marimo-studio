import type {
  ActiveViewRequest,
  ObserveViewRequest,
} from "@marimo-studio/protocol/development-events";

import { beforeEach, expect, it, vi } from "vite-plus/test";

import type { ViewLanding } from "../src/features/views/transition.ts";

import { WorkspaceEventCoordinator } from "../src/app/workspace-event-coordinator.ts";

class EventSourceStub {
  static instances: EventSourceStub[] = [];
  readonly listeners = new Map<string, EventListener>();
  closed = false;

  constructor(readonly url: string) {
    EventSourceStub.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener): void {
    this.listeners.set(type, listener);
  }

  emit(type: string, data?: string): void {
    this.listeners.get(type)?.(
      data === undefined ? new Event(type) : new MessageEvent(type, { data }),
    );
  }

  close(): void {
    this.closed = true;
  }
}

const workspace = (initialViews = ["dashboard", "report"]) => {
  let current = "dashboard";
  let views = [...initialViews];
  const listeners = new Set<() => void>();
  const choose = vi.fn(async (view: string, _landing: ViewLanding) => {
    if (!views.includes(view)) {
      return false;
    }
    current = view;
    listeners.forEach((listener) => listener());
    return true;
  });
  const ensureAvailable = vi.fn(async (view: string) => views.includes(view));
  const refreshInventory = vi.fn(async () => undefined);
  return {
    views: {
      subscribe(listener: () => void) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      getSnapshot: () => ({ current }),
      refreshInventory,
      ensureAvailable,
      choose,
    },
    choose,
    ensureAvailable,
    refreshInventory,
    replaceViews(next: string[]) {
      views = next;
    },
  };
};

const setup = (
  initialViews?: string[],
  initialActivation?: ActiveViewRequest,
  failFirstActivation = false,
) => {
  const model = workspace(initialViews);
  const preview = {
    requestObservation: vi.fn(),
    editorSessionChanged: vi.fn(),
    reload: vi.fn(),
    sourceBaseline: vi.fn(),
    sourceChanged: vi.fn(),
  };
  const source = { reconcile: vi.fn(), externalChanges: vi.fn() };
  const acknowledge = vi.fn(
    async (_generation: number, _view: string, _signal: AbortSignal) => undefined,
  );
  if (failFirstActivation) {
    acknowledge.mockRejectedValueOnce(new Error("temporary acknowledgement failure"));
  }
  const coordinator = new WorkspaceEventCoordinator({
    eventsUrl: "/events?file=notebook.py",
    views: model.views,
    preview,
    source,
    acknowledge,
  });
  coordinator.start(initialActivation);
  return { acknowledge, coordinator, model, preview, source };
};

beforeEach(() => {
  EventSourceStub.instances = [];
  vi.stubGlobal("EventSource", EventSourceStub);
});

it("reconnects the workspace stream after a committed view selection", async () => {
  const { coordinator, model } = setup();
  expect(EventSourceStub.instances).toHaveLength(1);
  expect(EventSourceStub.instances[0]?.url).toContain("marimo_studio_view=dashboard");

  await model.views.choose("report", "preserve");

  expect(EventSourceStub.instances).toHaveLength(2);
  expect(EventSourceStub.instances[0]?.closed).toBe(true);
  expect(EventSourceStub.instances[1]?.url).toContain("marimo_studio_view=report");
  coordinator.dispose();
});

it("routes source events to inventory reconciliation", async () => {
  const { coordinator, model, preview, source } = setup();
  EventSourceStub.instances[0]?.emit(
    "ready",
    JSON.stringify({ schema: 1, view: "dashboard", revision: "presentation-v1" }),
  );
  EventSourceStub.instances[0]?.emit(
    "change",
    JSON.stringify({
      kind: "css",
      files: [{ path: "app.css", revision: "sha256:next" }],
    }),
  );

  await vi.waitFor(() => expect(model.refreshInventory).toHaveBeenCalledTimes(2));
  expect(source.reconcile).toHaveBeenCalledOnce();
  expect(preview.sourceBaseline).toHaveBeenCalledWith("presentation-v1");
  expect(preview.sourceChanged).toHaveBeenCalledWith("css");
  expect(source.externalChanges).toHaveBeenCalledWith([
    { path: "app.css", revision: "sha256:next" },
  ]);
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
  expect(model.ensureAvailable).toHaveBeenCalledWith("report");
  expect(model.choose).toHaveBeenCalledWith("report", "split");
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
  expect(model.choose).toHaveBeenCalledWith("dashboard", "split");
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

  EventSourceStub.instances[1]?.emit("activate", JSON.stringify(activation));
  await vi.waitFor(() => expect(acknowledge).toHaveBeenCalledTimes(2));

  expect(EventSourceStub.instances).toHaveLength(2);
  warning.mockRestore();
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

it("selects an unfocused observation before forwarding it", async () => {
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

  await vi.waitFor(() => expect(preview.requestObservation).toHaveBeenCalledWith(request));
  expect(model.choose).toHaveBeenCalledWith("report", "preserve");
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
