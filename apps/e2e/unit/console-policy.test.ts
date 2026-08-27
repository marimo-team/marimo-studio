import { expect, test } from "vite-plus/test";

import { shouldRecordConsoleMessage } from "../tests/console-policy.ts";

test("records browser warnings and errors while network failures stay request-owned", () => {
  expect(shouldRecordConsoleMessage("warning", "Query synchronization failed")).toBe(true);
  expect(shouldRecordConsoleMessage("error", "Activation failed")).toBe(true);
  expect(shouldRecordConsoleMessage("log", "UIElementRegistry missing entry for control")).toBe(
    true,
  );
  expect(shouldRecordConsoleMessage("log", "runtime ready")).toBe(false);
  expect(shouldRecordConsoleMessage("error", "Failed to load resource: net::ERR_ABORTED")).toBe(
    false,
  );
  expect(
    shouldRecordConsoleMessage(
      "warning",
      "The resource http://127.0.0.1:4321/_marimo-studio/editor/assets/gradient-test.png was preloaded using link preload but not used within a few seconds.",
    ),
  ).toBe(true);
  expect(
    shouldRecordConsoleMessage(
      "warning",
      "The resource http://127.0.0.1:4321/app.js was preloaded using link preload but not used.",
    ),
  ).toBe(true);
});
