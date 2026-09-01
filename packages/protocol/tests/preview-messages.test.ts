import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import type { JsonValue } from "../src/runtime-config.ts";

import { parsePreviewMessage, previewMessageFitsBudget } from "../src/preview-messages.ts";
import { emptyProjectionEvidence } from "./fixtures.ts";

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

const observation = ({
  diagnosticCount = 0,
  diagnosticSize = 0,
  projectionCount = 1,
  targetSize = 1,
}: {
  diagnosticCount?: number;
  diagnosticSize?: number;
  projectionCount?: number;
  targetSize?: number;
}) => ({
  type: "marimo-studio:view-observation",
  runtime: "server",
  lifecycleId: 7,
  view: "dashboard",
  revision: "presentation-v2",
  state: "loading",
  diagnostics: Array.from({ length: diagnosticCount }, () => diagnostic(diagnosticSize)),
  runtimeInstance: "runtime-instance",
  sessionId: "s_123456",
  requestId: "request-dashboard",
  query: "",
  projectionInstances: Array.from({ length: projectionCount }, (_, index) => ({
    mountId: `mount-${index}`,
    instanceId: `instance-${index}`,
    target: "x".repeat(targetSize),
    runtimeCellId: `cell-${index}`,
    phase: "loading",
    error: null,
  })),
});

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
  {
    type: "marimo-studio:view-observation",
    runtime: "server",
    lifecycleId: 7,
    view,
    revision: "presentation-v2",
    state: "loading",
    diagnostics: [],
    runtimeInstance: "runtime-instance",
    sessionId: "s_123456",
    requestId: "request-view",
    query: "",
    projectionInstances: [],
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
      type: "marimo-studio:view-observation",
      runtime: "server",
      lifecycleId: 7,
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
      ...emptyProjectionEvidence,
    },
    {
      type: "marimo-studio:observe-view",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      revision: "presentation-v2",
      runtimeInstance: "runtime-instance",
      requestId: "request-dashboard",
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
  for (const length of [128, 129, 228, 229, 240]) {
    for (const message of viewIdentityMessages("v".repeat(length))) {
      assert.notEqual(parsePreviewMessage(message), undefined, `${length}: ${message.type}`);
    }
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
    {
      type: "marimo-studio:observe-view",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      revision: "presentation-v2",
      runtimeInstance: "r".repeat(257),
      requestId: "request-dashboard",
    },
    {
      type: "marimo-studio:observe-view",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      revision: "presentation-v2",
      runtimeInstance: "runtime-instance",
      requestId: "q".repeat(257),
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

test("preview observations reserve the larger evidence budget", () => {
  const normal = observation({});
  const large = observation({ projectionCount: 512, targetSize: 1_024 });
  const overLimit = observation({
    diagnosticCount: 200,
    diagnosticSize: 6_000,
    projectionCount: 512,
    targetSize: 4_096,
  });

  assert.ok(encodedLength(normal) < 256 * 1_024);
  assert.ok(encodedLength(large) > 256 * 1_024);
  assert.ok(encodedLength(large) < 4 * 1_024 * 1_024);
  assert.ok(encodedLength(overLimit) > 4 * 1_024 * 1_024);
  assert.notEqual(parsePreviewMessage(normal), undefined);
  assert.notEqual(parsePreviewMessage(large), undefined);
  assert.equal(parsePreviewMessage(overLimit), undefined);
});
