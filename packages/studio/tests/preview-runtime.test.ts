import { expect, test } from "vite-plus/test";

import { initialPreviewRuntime } from "../src/preview/runtime";

test("preview runtime selection restores valid choices and discards stale ones", () => {
  const selection = (stored: string) =>
    initialPreviewRuntime({
      available: ["server", "wasm"],
      configured: "server",
      stored,
    });

  expect(selection("wasm")).toBe("wasm");
  expect(selection("custom")).toBe("server");
});
