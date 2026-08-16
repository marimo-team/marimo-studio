import { runtimeIdSchema } from "@marimo-studio/protocol/runtime-config";
import { RUNTIME_QUERY_KEY } from "@marimo-studio/protocol/runtime-selection";
import { z } from "zod";

const PENDING_RUNTIME_STATE_KEY = "marimo-studio:pending-runtime:v1";

const pendingRuntimeStateSchema = z.object({
  [PENDING_RUNTIME_STATE_KEY]: z.object({
    runtime: runtimeIdSchema,
    previous: z.unknown(),
  }),
});

const pendingRuntimeState = () => {
  const parsed = pendingRuntimeStateSchema.safeParse(globalThis.history.state);
  if (!parsed.success) {
    return undefined;
  }
  return parsed.data[PENDING_RUNTIME_STATE_KEY];
};

export const restorePendingRuntimeSelection = (): void => {
  const url = new URL(globalThis.location.href);
  if (url.searchParams.has(RUNTIME_QUERY_KEY)) {
    return;
  }
  const pending = pendingRuntimeState();
  if (!pending) {
    return;
  }
  url.searchParams.set(RUNTIME_QUERY_KEY, pending.runtime);
  globalThis.history.replaceState(pending.previous, "", url);
};

export const hideRuntimeSelectionDuringStartup = (): (() => void) => {
  const selected = new URL(globalThis.location.href).searchParams.get(RUNTIME_QUERY_KEY);
  const parsed = runtimeIdSchema.safeParse(selected);
  if (!parsed.success) {
    return () => {};
  }
  const clean = new URL(globalThis.location.href);
  clean.searchParams.delete(RUNTIME_QUERY_KEY);
  globalThis.history.replaceState(
    {
      [PENDING_RUNTIME_STATE_KEY]: {
        runtime: parsed.data,
        previous: globalThis.history.state,
      },
    },
    "",
    clean,
  );
  return () => {
    const current = new URL(globalThis.location.href);
    current.searchParams.set(RUNTIME_QUERY_KEY, parsed.data);
    const pending = pendingRuntimeState();
    globalThis.history.replaceState(
      pending?.runtime === parsed.data ? pending.previous : globalThis.history.state,
      "",
      current,
    );
  };
};
