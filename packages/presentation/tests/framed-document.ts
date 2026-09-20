import { afterEach, beforeEach, vi } from "vite-plus/test";

beforeEach(() => {
  vi.stubGlobal("parent", { postMessage: vi.fn() });
});

afterEach(() => {
  vi.unstubAllGlobals();
});
