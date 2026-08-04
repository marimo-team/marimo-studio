import { afterEach, describe, expect, test, vi } from "vite-plus/test";

import {
  hideRuntimeSelectionDuringStartup,
  restorePendingRuntimeSelection,
} from "../src/runtime/selection";

class MemoryStorage {
  readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

const installBrowser = (href: string) => {
  let location = new URL(href);
  const storage = new MemoryStorage();
  vi.stubGlobal("location", location);
  vi.stubGlobal("sessionStorage", storage);
  vi.stubGlobal("history", {
    state: null,
    replaceState: (_state: unknown, _title: string, next: string | URL) => {
      location = new URL(next, location);
      vi.stubGlobal("location", location);
    },
  });
  return { location: () => location, storage };
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("pending runtime selection", () => {
  test("survives reload during startup and clears recovery state after mounting", () => {
    const browser = installBrowser("https://example.test/dashboard/?runtime=wasm");

    hideRuntimeSelectionDuringStartup();
    expect(browser.location().search).toBe("");

    restorePendingRuntimeSelection();
    expect(browser.location().search).toBe("?runtime=wasm");

    const restore = hideRuntimeSelectionDuringStartup();
    restore();

    expect(browser.location().search).toBe("?runtime=wasm");
    expect(browser.storage.values.size).toBe(0);
  });
});
