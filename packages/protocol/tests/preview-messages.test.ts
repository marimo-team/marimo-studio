import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import type { JsonValue } from "../src/runtime-config.ts";

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
      type: "marimo-studio:view-observation",
      runtime: "server",
      view: "dashboard",
      revision: "presentation-v2",
      state: "error",
      diagnostics: [
        {
          code: "missing-variable",
          severity: "error",
          message: "summary is unavailable.",
          hint: "Restore summary in the notebook.",
          view: "dashboard",
          scope: "host",
          target: "summary",
        },
      ],
      runtimeInstance: "runtime-instance",
      sessionId: "s_123456",
      requestId: "request-dashboard",
      query: "region=emea",
    }),
    {
      type: "marimo-studio:view-observation",
      runtime: "server",
      view: "dashboard",
      revision: "presentation-v2",
      state: "error",
      diagnostics: [
        {
          code: "missing-variable",
          severity: "error",
          message: "summary is unavailable.",
          hint: "Restore summary in the notebook.",
          view: "dashboard",
          scope: "host",
          target: "summary",
        },
      ],
      runtimeInstance: "runtime-instance",
      sessionId: "s_123456",
      requestId: "request-dashboard",
      query: "region=emea",
    },
  );
  assert.deepEqual(
    parsePreviewMessage({
      type: "marimo-studio:observe-view",
      runtime: "server",
      view: "dashboard",
      revision: "presentation-v2",
      runtimeInstance: "runtime-instance",
      requestId: "request-dashboard",
    }),
    {
      type: "marimo-studio:observe-view",
      runtime: "server",
      view: "dashboard",
      revision: "presentation-v2",
      runtimeInstance: "runtime-instance",
      requestId: "request-dashboard",
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
      type: "marimo-studio:receiver-unready",
      runtime: "server",
      view: "dashboard",
    }),
    {
      type: "marimo-studio:receiver-unready",
      runtime: "server",
      view: "dashboard",
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
      type: "marimo-studio:source-change",
      runtime: "server",
      view: "dashboard",
      kind: "runtime",
    }),
    {
      type: "marimo-studio:source-change",
      runtime: "server",
      view: "dashboard",
      kind: "runtime",
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
  const malformed: JsonValue[] = [
    null,
    { type: "marimo-studio:navigate-view", view: 42 },
    { type: "marimo-studio:source-change", runtime: "server", view: "dashboard", kind: "js" },
    { type: "unknown", view: "dashboard" },
  ];

  malformed.forEach((message) => assert.deepEqual(parsePreviewMessage(message), undefined));
});
