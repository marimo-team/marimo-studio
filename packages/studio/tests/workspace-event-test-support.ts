import type { ActiveViewRequest } from "@marimo-studio/protocol/development-events";

import { vi } from "vite-plus/test";

import type { ViewLanding } from "../src/features/views/transition.ts";

import { WorkspaceEventCoordinator } from "../src/app/workspace-event-coordinator.ts";

export const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
};

export class EventSourceStub {
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
  let selecting: string | undefined;
  let nextSelection: Promise<boolean> | undefined;
  let views = [...initialViews];
  const listeners = new Set<() => void>();
  const choose = vi.fn(async (view: string, _landing: ViewLanding) => {
    if (!views.includes(view)) {
      return false;
    }
    selecting = view;
    listeners.forEach((listener) => listener());
    const accepted = await (nextSelection ?? true);
    nextSelection = undefined;
    if (!accepted) {
      selecting = undefined;
      listeners.forEach((listener) => listener());
      return false;
    }
    current = view;
    selecting = undefined;
    listeners.forEach((listener) => listener());
    return true;
  });
  const ensureAvailable = vi.fn(async (view: string) => views.includes(view));
  const refreshInventory = vi.fn(async () => undefined);
  const cancelPendingSelection = vi.fn();
  return {
    views: {
      subscribe(listener: () => void) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      getSnapshot: () => ({ current, selecting }),
      refreshInventory,
      ensureAvailable,
      choose,
      cancelPendingSelection,
    },
    cancelPendingSelection,
    choose,
    ensureAvailable,
    refreshInventory,
    deferNextSelection(selection: Promise<boolean>) {
      nextSelection = selection;
    },
    replaceViews(next: string[]) {
      views = next;
    },
  };
};

export const setup = (
  initialViews?: string[],
  initialActivation?: ActiveViewRequest,
  failFirstActivation = false,
) => {
  const model = workspace(initialViews);
  const preview = {
    automationTarget: vi.fn(async (_view: string, _reload: boolean, _signal: AbortSignal) => ({
      previewUrl: "http://localhost/preview/",
      frameSelector: "iframe[data-test-preview]",
    })),
    requestObservation: vi.fn(),
    editorSessionChanged: vi.fn(),
    reload: vi.fn(),
    presentationBaseline: vi.fn(),
    presentationBuildStarted: vi.fn(),
    presentationBuildCompleted: vi.fn(),
    presentationStreamAbandoned: vi.fn(),
    presentationChanged: vi.fn(),
  };
  const source = { reconcile: vi.fn(), externalChanges: vi.fn() };
  const acknowledge = vi.fn(
    async (
      _activation: ActiveViewRequest,
      _preview: { previewUrl: string; frameSelector: string },
      _signal: AbortSignal,
    ) => undefined,
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
