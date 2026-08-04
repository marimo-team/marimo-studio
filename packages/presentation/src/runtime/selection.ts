import { runtimeIdSchema } from "@marimo-studio/protocol/runtime-config";
import { RUNTIME_QUERY_KEY } from "@marimo-studio/protocol/runtime-selection";

const storageKey = (): string => `marimo-studio:pending-runtime:v1:${globalThis.location.pathname}`;

const replaceLocation = (url: URL): void => {
  globalThis.history.replaceState(globalThis.history.state, "", url);
};

export const restorePendingRuntimeSelection = (): void => {
  const url = new URL(globalThis.location.href);
  if (url.searchParams.has(RUNTIME_QUERY_KEY)) {
    return;
  }
  const parsed = runtimeIdSchema.safeParse(globalThis.sessionStorage.getItem(storageKey()));
  if (!parsed.success) {
    return;
  }
  url.searchParams.set(RUNTIME_QUERY_KEY, parsed.data);
  replaceLocation(url);
};

export const hideRuntimeSelectionDuringStartup = (): (() => void) => {
  const selected = new URL(globalThis.location.href).searchParams.get(RUNTIME_QUERY_KEY);
  const parsed = runtimeIdSchema.safeParse(selected);
  if (!parsed.success) {
    return () => {};
  }
  const key = storageKey();
  globalThis.sessionStorage.setItem(key, parsed.data);
  const clean = new URL(globalThis.location.href);
  clean.searchParams.delete(RUNTIME_QUERY_KEY);
  replaceLocation(clean);
  return () => {
    const current = new URL(globalThis.location.href);
    current.searchParams.set(RUNTIME_QUERY_KEY, parsed.data);
    replaceLocation(current);
    globalThis.sessionStorage.removeItem(key);
  };
};
