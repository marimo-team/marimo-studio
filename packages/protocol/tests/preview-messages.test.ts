import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import type { JsonValue } from "../src/runtime-config.ts";

import { parsePreviewMessage, previewMessageFitsBudget } from "../src/preview-messages.ts";

const pendingDiagnostic = {
  code: "notebook-updating",
  severity: "warning" as const,
  message: "The notebook is updating.",
  hint: "Wait for the current notebook run.",
  view: "dashboard",
  scope: "runtime",
};

const diagnostic = (textSize: number) => ({
  ...pendingDiagnostic,
  message: "m".repeat(textSize),
  hint: "h".repeat(textSize),
});

const encodedLength = (value: JsonValue): number =>
  new TextEncoder().encode(JSON.stringify(value)).byteLength;

const viewIdentityMessages = (view: string) => [
  {
    type: "marimo-studio:switch-view",
    runtime: "server",
    lifecycleId: 7,
    view,
    documentUrl: "/view/",
    supportUrl: "/_marimo-studio/views/view",
  },
  {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 7,
    view,
    revision: "presentation-v2",
  },
];

interface CyclicPreviewProbe {
  readonly type: string;
  readonly runtime: string;
  readonly lifecycleId: number;
  readonly query: string;
  self?: CyclicPreviewProbe;
}

interface DeepPreviewProbe {
  readonly nested: string | DeepPreviewProbe;
}

test("preview messages decode every supported discriminant", () => {
  const messages: JsonValue[] = [
    {
      type: "marimo-studio:navigate-view",
      runtime: "server",
      lifecycleId: 7,
      view: "report",
      query: "?region=emea",
      hash: "#details",
      history: "push",
    },
    {
      type: "marimo-studio:replay-document",
      runtime: "server",
      lifecycleId: 7,
      view: "report",
      url: "/_marimo-studio/presentation/d.example/report/",
    },
    {
      type: "marimo-studio:query-change",
      runtime: "server",
      lifecycleId: 7,
      query: "?region=emea",
    },
    {
      type: "marimo-studio:restore-fragment",
      runtime: "server",
      lifecycleId: 7,
      hash: "#details",
    },
    {
      type: "marimo-studio:receiver-ready",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      revision: "presentation-v1",
    },
    {
      type: "marimo-studio:receiver-unready",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
    },
    {
      type: "marimo-studio:receiver-waiting",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
    },
    {
      type: "marimo-studio:view-ready",
      runtime: "wasm",
      lifecycleId: 7,
      view: "report",
      revision: "presentation-v1",
    },
    {
      type: "marimo-studio:view-sync-pending",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      diagnostic: pendingDiagnostic,
    },
    {
      type: "marimo-studio:view-error",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      revision: "presentation-v2",
      sessionId: "s_123456",
      diagnostic: pendingDiagnostic,
    },
    {
      type: "marimo-studio:view-error",
      runtime: "wasm",
      lifecycleId: 7,
      view: "dashboard",
      revision: "presentation-v2",
      sessionId: null,
      diagnostic: pendingDiagnostic,
    },
    {
      type: "marimo-studio:presentation-change",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
    },
    {
      type: "marimo-studio:presentation-refresh",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      phase: "pending",
    },
    {
      type: "marimo-studio:presentation-refresh-barrier",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      generation: 3,
    },
    {
      type: "marimo-studio:receiver-admitted",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      revision: "presentation-v2",
    },
    {
      type: "marimo-studio:switch-view",
      runtime: "wasm",
      view: "report",
      lifecycleId: 7,
      documentUrl: "/report/",
      supportUrl: "/_marimo-studio/views/report",
    },
    {
      type: "marimo-studio:view-diagnostics",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      diagnostics: [pendingDiagnostic],
    },
  ];

  messages.forEach((message) =>
    assert.deepEqual(parsePreviewMessage(message), message, JSON.stringify(message)),
  );
});

test("preview view identities use the portable 240-byte contract", () => {
  for (const message of viewIdentityMessages("v".repeat(240))) {
    assert.notEqual(parsePreviewMessage(message), undefined, message.type);
  }
  for (const message of viewIdentityMessages("v".repeat(241))) {
    assert.equal(parsePreviewMessage(message), undefined, message.type);
  }
});

test("preview messages reject malformed protocol classes", () => {
  const malformed: JsonValue[] = [
    null,
    { type: "unknown", view: "dashboard" },
    {
      type: "marimo-studio:query-change",
      runtime: "server",
      query: "?region=emea",
    },
    {
      type: "marimo-studio:receiver-ready",
      runtime: "server",
      lifecycleId: 7,
      revision: "",
      extra: true,
    },
    {
      type: "marimo-studio:view-error",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      diagnostic: { ...pendingDiagnostic, view: "report" },
    },
    {
      type: "marimo-studio:view-error",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      revision: "presentation-v2",
      sessionId: "",
      diagnostic: pendingDiagnostic,
    },
  ];

  malformed.forEach((message) => assert.deepEqual(parsePreviewMessage(message), undefined));
});

test("preview message budgets reject cyclic and deeply nested structured-clone graphs", () => {
  const cyclic: CyclicPreviewProbe = {
    type: "marimo-studio:query-change",
    runtime: "server",
    lifecycleId: 7,
    query: "",
  };
  cyclic.self = cyclic;
  let deep: string | DeepPreviewProbe = "leaf";
  for (let index = 0; index < 40; index += 1) {
    deep = { nested: deep };
  }

  assert.equal(previewMessageFitsBudget(cyclic), false);
  assert.equal(previewMessageFitsBudget(deep), false);
  assert.equal(parsePreviewMessage(cyclic), undefined);
  assert.equal(parsePreviewMessage(deep), undefined);
});

test("preview mutation messages reject oversized domain fields", () => {
  const oversized: JsonValue[] = [
    {
      type: "marimo-studio:query-change",
      runtime: "server",
      lifecycleId: 7,
      query: `?${"q".repeat(16_384)}`,
    },
    {
      type: "marimo-studio:navigate-view",
      runtime: "server",
      lifecycleId: 7,
      view: "report",
      query: `?${"q".repeat(16_384)}`,
      hash: "",
    },
    {
      type: "marimo-studio:navigate-view",
      runtime: "server",
      lifecycleId: 7,
      view: "report",
      query: "",
      hash: `#${"é".repeat(4_096)}`,
    },
    {
      type: "marimo-studio:navigate-view",
      runtime: "server",
      lifecycleId: 7,
      view: "v".repeat(241),
      query: "",
      hash: "",
    },
    {
      type: "marimo-studio:switch-view",
      runtime: "server",
      lifecycleId: 7,
      view: "report",
      documentUrl: `/${"x".repeat(32_768)}`,
      supportUrl: "/_marimo-studio/views/report",
    },
    {
      type: "marimo-studio:view-sync-pending",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      diagnostic: {
        ...pendingDiagnostic,
        message: "é".repeat(32_769),
      },
    },
    {
      type: "marimo-studio:view-ready",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      revision: "r".repeat(257),
    },
    {
      type: "marimo-studio:view-ready",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      revision: "presentation-v2",
      sessionId: "s".repeat(257),
    },
  ];

  oversized.forEach((message) => assert.equal(parsePreviewMessage(message), undefined));
});

test("ordinary preview messages retain the browser message budget", () => {
  const message = (count: number) => ({
    type: "marimo-studio:view-diagnostics",
    runtime: "server",
    lifecycleId: 7,
    view: "dashboard",
    diagnostics: Array.from({ length: count }, () => diagnostic(1_024)),
  });
  const normal = message(80);
  const oversized = message(160);

  assert.ok(encodedLength(normal) < 256 * 1_024);
  assert.ok(encodedLength(oversized) > 256 * 1_024);
  assert.notEqual(parsePreviewMessage(normal), undefined);
  assert.equal(parsePreviewMessage(oversized), undefined);
});
