import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { parsePreviewMessage } from "../src/preview-messages.ts";

test("preview messages decode navigation and view state", () => {
  assert.deepEqual(
    parsePreviewMessage({
      type: "marimo-studio:view-ready",
      runtime: "wasm",
      view: "report",
      revision: "presentation-v1",
    }),
    {
      type: "marimo-studio:view-ready",
      runtime: "wasm",
      view: "report",
      revision: "presentation-v1",
    },
  );
  assert.deepEqual(
    parsePreviewMessage({
      type: "marimo-studio:navigate-view",
      runtime: "wasm",
      view: "report",
    }),
    {
      type: "marimo-studio:navigate-view",
      runtime: "wasm",
      view: "report",
    },
  );
  assert.deepEqual(
    parsePreviewMessage({
      type: "marimo-studio:view-sync-pending",
      runtime: "server",
      view: "dashboard",
      message: "The notebook is updating.",
    }),
    {
      type: "marimo-studio:view-sync-pending",
      runtime: "server",
      view: "dashboard",
      message: "The notebook is updating.",
      hint: "The notebook is updating.",
    },
  );
  assert.deepEqual(
    parsePreviewMessage({
      type: "marimo-studio:switch-view",
      runtime: "wasm",
      view: "report",
      documentUrl: "/report/",
      supportUrl: "/_marimo-studio/views/report",
    }),
    {
      type: "marimo-studio:switch-view",
      runtime: "wasm",
      view: "report",
      documentUrl: "/report/",
      supportUrl: "/_marimo-studio/views/report",
    },
  );
  assert.deepEqual(
    parsePreviewMessage({
      type: "marimo-studio:view-diagnostics",
      runtime: "server",
      view: "dashboard",
      diagnostics: [{ message: "Cell summary is unavailable." }],
    }),
    {
      type: "marimo-studio:view-diagnostics",
      runtime: "server",
      view: "dashboard",
      diagnostics: [{ message: "Cell summary is unavailable." }],
    },
  );
});

test("preview messages reject malformed protocol payloads", () => {
  const malformed = [
    null,
    { type: "marimo-studio:navigate-view", view: 42 },
    { type: "unknown", view: "dashboard" },
  ];

  malformed.forEach((message) => assert.deepEqual(parsePreviewMessage(message), undefined));
});
