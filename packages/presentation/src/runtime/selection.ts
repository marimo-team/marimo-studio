import { runtimeIdSchema } from "@marimo-studio/protocol/runtime-config";
import { RUNTIME_QUERY_KEY } from "@marimo-studio/protocol/runtime-selection";

const PENDING_RUNTIME_STATE_KEY = "marimo-studio:pending-runtime:v1";

interface PendingRuntimeState {
  runtime: string;
  previous: unknown;
}

const pendingRuntimeState = (state: unknown): PendingRuntimeState | undefined => {
  if (typeof state !== "object" || state === null) {
    return undefined;
  }
  const pending = (state as Record<string, unknown>)[PENDING_RUNTIME_STATE_KEY];
  if (typeof pending !== "object" || pending === null || !("previous" in pending)) {
    return undefined;
  }
  const parsed = runtimeIdSchema.safeParse((pending as Record<string, unknown>).runtime);
  if (!parsed.success) {
    return undefined;
  }
  return {
    runtime: parsed.data,
    previous: (pending as Record<string, unknown>).previous,
  };
};

const replaceLocation = (url: URL, state: unknown = globalThis.history.state): void => {
  globalThis.history.replaceState(state, "", url);
};

export const restorePendingRuntimeSelection = (): void => {
  const url = new URL(globalThis.location.href);
  if (url.searchParams.has(RUNTIME_QUERY_KEY)) {
    return;
  }
  const pending = pendingRuntimeState(globalThis.history.state);
  if (!pending) {
    return;
  }
  url.searchParams.set(RUNTIME_QUERY_KEY, pending.runtime);
  replaceLocation(url, pending.previous);
};

export const hideRuntimeSelectionDuringStartup = (): (() => void) => {
  const selected = new URL(globalThis.location.href).searchParams.get(RUNTIME_QUERY_KEY);
  const parsed = runtimeIdSchema.safeParse(selected);
  if (!parsed.success) {
    return () => {};
  }
  const clean = new URL(globalThis.location.href);
  clean.searchParams.delete(RUNTIME_QUERY_KEY);
  replaceLocation(clean, {
    [PENDING_RUNTIME_STATE_KEY]: {
      runtime: parsed.data,
      previous: globalThis.history.state,
    },
  });
  return () => {
    const current = new URL(globalThis.location.href);
    current.searchParams.set(RUNTIME_QUERY_KEY, parsed.data);
    const pending = pendingRuntimeState(globalThis.history.state);
    replaceLocation(
      current,
      pending?.runtime === parsed.data ? pending.previous : globalThis.history.state,
    );
  };
};
