import {
  frameControlUpdatesSchema,
  parseFrameBridgeMessage,
  type FrameBridgeMessage,
  type FrameControlUpdate,
} from "@marimo-studio/protocol/frame-bridge";

import type { ControlEndpoint } from "./control-sync.ts";

interface PendingRequest {
  kind: "control" | "query";
  reject(error: Error): void;
  resolve(): void;
  timer: ReturnType<typeof setTimeout>;
}

interface FrameBridgeState {
  controls: Map<string, FrameControlUpdate>;
  generation: string;
  identity: FrameIdentity;
  listeners: Set<(update: FrameControlUpdate) => void>;
  pending: Map<string, PendingRequest>;
  source: Window;
}

interface FrameIdentity {
  lifecycleId: number;
  revision: string;
  runtime: string;
  sessionId: string | null;
  view: string;
}

const bridges = new WeakMap<Window, FrameBridgeState>();
let requestSequence = 0;

const messageIdentity = (message: FrameBridgeMessage): FrameIdentity => ({
  lifecycleId: message.lifecycleId,
  revision: message.revision,
  runtime: message.runtime,
  sessionId: message.sessionId,
  view: message.view,
});

const sameIdentity = (left: FrameIdentity, right: FrameIdentity): boolean =>
  left.lifecycleId === right.lifecycleId &&
  left.revision === right.revision &&
  left.runtime === right.runtime &&
  left.sessionId === right.sessionId &&
  left.view === right.view;

const frameForSource = (source: MessageEventSource | null): HTMLIFrameElement | undefined =>
  Array.from(document.querySelectorAll<HTMLIFrameElement>("iframe[data-preview-frame]")).find(
    (frame) => frame.contentWindow === source,
  );

const expectedLifecycle = (frame: HTMLIFrameElement): number | undefined => {
  const value = frame.dataset.previewLifecycleId;
  return value && /^[1-9][0-9]*$/.test(value) ? Number(value) : undefined;
};

const rejectPending = (state: FrameBridgeState, message: string): void => {
  state.pending.forEach((pending) => {
    clearTimeout(pending.timer);
    pending.reject(new Error(message));
  });
  state.pending.clear();
};

const receive = (event: MessageEvent<unknown>): void => {
  if (event.origin !== "null" && event.origin !== globalThis.location.origin) {
    return;
  }
  const message = parseFrameBridgeMessage(event.data);
  const frame = frameForSource(event.source);
  const source = frame?.contentWindow;
  if (!message || !frame || !source || expectedLifecycle(frame) !== message.lifecycleId) {
    return;
  }
  if (message.type === "marimo-studio:frame-bridge-ready") {
    const previous = bridges.get(source);
    const identity = messageIdentity(message);
    if (
      previous &&
      previous.generation === message.generation &&
      sameIdentity(previous.identity, identity)
    ) {
      const controls = new Map(message.controls.map((update) => [update.objectId, update]));
      previous.controls.forEach((_update, objectId) => {
        if (!controls.has(objectId)) {
          previous.controls.delete(objectId);
        }
      });
      controls.forEach((update, objectId) => {
        const current = previous.controls.get(objectId);
        previous.controls.set(objectId, update);
        if (
          current !== undefined &&
          JSON.stringify(current.value) !== JSON.stringify(update.value)
        ) {
          previous.listeners.forEach((listener) => listener(update));
        }
      });
      return;
    }
    if (previous) {
      rejectPending(previous, "The presentation document changed");
    }
    bridges.set(source, {
      controls: new Map(message.controls.map((update) => [update.objectId, update])),
      generation: message.generation,
      identity,
      listeners: new Set(),
      pending: new Map(),
      source,
    });
    return;
  }
  const state = bridges.get(source);
  if (
    !state ||
    state.generation !== message.generation ||
    !sameIdentity(state.identity, messageIdentity(message))
  ) {
    return;
  }
  if (message.type === "marimo-studio:frame-control-update") {
    state.controls.set(message.update.objectId, message.update);
    state.listeners.forEach((listener) => listener(message.update));
    return;
  }
  if (
    message.type === "marimo-studio:frame-control-applied" ||
    message.type === "marimo-studio:frame-query-applied"
  ) {
    const pending = state.pending.get(message.requestId);
    const kind = message.type.includes("control") ? "control" : "query";
    if (!pending || pending.kind !== kind) {
      return;
    }
    clearTimeout(pending.timer);
    state.pending.delete(message.requestId);
    if (message.error) {
      pending.reject(new Error(message.error));
    } else {
      pending.resolve();
    }
  }
};

globalThis.addEventListener("message", receive);

const stateFor = (frame: HTMLIFrameElement): FrameBridgeState | undefined => {
  const source = frame.contentWindow;
  const state = source ? bridges.get(source) : undefined;
  return state && state.identity.lifecycleId === expectedLifecycle(frame) ? state : undefined;
};

const request = (
  state: FrameBridgeState,
  kind: PendingRequest["kind"],
  payload: FrameBridgeMessage,
): Promise<void> =>
  new Promise((resolve, reject) => {
    const requestId = "requestId" in payload ? payload.requestId : undefined;
    if (!requestId) {
      reject(new Error("Frame bridge request ID is missing"));
      return;
    }
    const timer = setTimeout(() => {
      state.pending.delete(requestId);
      reject(new Error(`Presentation ${kind} synchronization timed out`));
    }, 3_000);
    state.pending.set(requestId, { kind, reject, resolve, timer });
    state.source.postMessage(payload, "*");
  });

const requestId = (): string =>
  `bridge_${Date.now().toString(36)}_${(++requestSequence).toString(36)}`;

export const connectFrameControlBridge = (
  frame: HTMLIFrameElement,
  expected: { revision: string; runtime: string; sessionId?: string },
): ControlEndpoint | undefined => {
  const state = stateFor(frame);
  if (
    !state ||
    state.identity.revision !== expected.revision ||
    state.identity.runtime !== expected.runtime ||
    state.identity.sessionId !== (expected.sessionId ?? null)
  ) {
    return undefined;
  }
  const listeners = new Set<(update: FrameControlUpdate) => void>();
  return {
    snapshot: () => Array.from(state.controls.values()),
    subscribe(listener) {
      listeners.add(listener);
      state.listeners.add(listener);
      return () => {
        listeners.delete(listener);
        state.listeners.delete(listener);
      };
    },
    apply: (updates) => {
      const accepted = frameControlUpdatesSchema.safeParse(updates);
      if (!accepted.success) {
        return Promise.reject(new Error("The presentation control updates are invalid"));
      }
      const id = requestId();
      return request(state, "control", {
        type: "marimo-studio:frame-control-apply",
        generation: state.generation,
        requestId: id,
        updates: accepted.data,
        ...state.identity,
      });
    },
    dispose() {
      listeners.forEach((listener) => state.listeners.delete(listener));
      listeners.clear();
    },
  };
};

export const applyFrameQuery = (
  frame: HTMLIFrameElement,
  query: string,
  hash?: string,
): Promise<void> => {
  const state = stateFor(frame);
  if (!state) {
    return Promise.reject(new Error("The presentation frame bridge is not ready"));
  }
  const id = requestId();
  const message: Extract<FrameBridgeMessage, { type: "marimo-studio:frame-query-apply" }> = {
    type: "marimo-studio:frame-query-apply",
    generation: state.generation,
    query,
    requestId: id,
    ...state.identity,
  };
  if (hash !== undefined) {
    message.hash = hash;
  }
  return request(state, "query", message);
};

export const resizeFrame = (frame: HTMLIFrameElement): void => {
  const state = stateFor(frame);
  if (!state) {
    return;
  }
  state.source.postMessage(
    {
      type: "marimo-studio:frame-resize",
      generation: state.generation,
      ...state.identity,
    } satisfies FrameBridgeMessage,
    "*",
  );
};

export const releaseFrameBridge = (frame: HTMLIFrameElement): void => {
  const source = frame.contentWindow;
  const state = source ? bridges.get(source) : undefined;
  if (!source || !state) {
    return;
  }
  rejectPending(state, "The presentation frame was released");
  state.listeners.clear();
  bridges.delete(source);
};
