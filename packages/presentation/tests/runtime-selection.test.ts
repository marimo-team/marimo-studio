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

interface BrowserInstallOptions {
  state?: History["state"];
  storage?: MemoryStorage;
}

const installBrowser = (
  href: string,
  { state: initialState = null, storage = new MemoryStorage() }: BrowserInstallOptions = {},
) => {
  let location = new URL(href);
  let state = initialState;
  vi.stubGlobal("location", location);
  vi.stubGlobal("sessionStorage", storage);
  vi.stubGlobal("history", {
    get state() {
      return state;
    },
    replaceState: (nextState: History["state"], _title: string, next: string | URL) => {
      state = nextState;
      location = new URL(next, location);
      vi.stubGlobal("location", location);
    },
  });
  return { location: () => location, state: () => state };
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("pending runtime selection", () => {
  test("survives reload during startup and clears recovery state after mounting", () => {
    const browser = installBrowser("https://example.test/dashboard/?runtime=wasm");

    hideRuntimeSelectionDuringStartup();
    expect(browser.location().search).toBe("");

    const reloaded = installBrowser(browser.location().href, { state: browser.state() });
    restorePendingRuntimeSelection();
    expect(reloaded.location().search).toBe("?runtime=wasm");

    const restore = hideRuntimeSelectionDuringStartup();
    restore();

    expect(reloaded.location().search).toBe("?runtime=wasm");
    expect(reloaded.state()).toBeNull();
  });

  test("keeps concurrent preview runtime selections isolated", () => {
    const storage = new MemoryStorage();
    installBrowser("https://example.test/dashboard/?runtime=wasm", { storage });
    hideRuntimeSelectionDuringStartup();

    const server = installBrowser("https://example.test/dashboard/", { storage });
    restorePendingRuntimeSelection();

    expect(server.location().search).toBe("");
  });
});
