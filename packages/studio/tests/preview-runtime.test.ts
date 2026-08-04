import { expect, test } from "vite-plus/test";

import { initialPreviewRuntime } from "../src/preview/runtime";

test("preview runtime selection starts from the configured runtime", () => {
  expect(
    initialPreviewRuntime({
      available: ["server", "wasm"],
      configured: "server",
    }),
  ).toBe("server");
  expect(
    initialPreviewRuntime({
      available: ["server", "wasm"],
      configured: "wasm",
    }),
  ).toBe("wasm");
});
