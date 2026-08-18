import type { BrowserDiagnostic } from "@marimo-studio/protocol/browser-observations";

import { expect, it } from "vite-plus/test";

import { PreviewDeck } from "../src/features/preview/deck.ts";
import { RuntimeDiagnostics } from "../src/features/preview/runtime-diagnostics.ts";
import { previewStatus } from "../src/features/preview/status.ts";

const warning: BrowserDiagnostic = {
  code: "value-stale",
  severity: "warning",
  message: "The projected value is stale.",
  hint: "Wait for the notebook to finish running.",
  view: "dashboard",
  scope: "projection",
  projection: "value",
  target: "summary.total",
};

it("retains transient runtime diagnostics after returning to ready", () => {
  let now = 1_000;
  const diagnostics = new RuntimeDiagnostics({
    runtime: "server",
    view: "dashboard",
    clock: () => now++,
  });

  diagnostics.record({
    phase: "degraded",
    revision: "revision-1",
    sessionId: "s_123456",
    diagnostics: [warning],
  });
  diagnostics.record({
    phase: "degraded",
    revision: "revision-1",
    sessionId: "s_123456",
    diagnostics: [warning],
  });
  diagnostics.record({ phase: "ready", diagnostics: [] });

  const report = diagnostics.report();
  expect(report.current).toEqual({ phase: "ready", diagnostics: [] });
  expect(report.transitions.map(({ phase }) => phase)).toEqual(["connecting", "degraded", "ready"]);
  expect(report.transitions[1]?.diagnostics).toEqual([warning]);
  expect(report.revision).toBe("revision-1");
  expect(report.sessionId).toBe("s_123456");
});

it("owns diagnostic evidence returned to callers", () => {
  const input: BrowserDiagnostic = {
    ...warning,
    source: { path: "dashboard.html", line: 4, column: 2 },
  };
  const diagnostics = new RuntimeDiagnostics({
    runtime: "server",
    view: "dashboard",
    clock: () => 1_000,
  });
  diagnostics.record({ phase: "degraded", diagnostics: [input] });

  input.message = "mutated input";
  if (input.source === undefined) {
    throw new Error("Test diagnostic source is unavailable");
  }
  input.source.line = 99;
  const exposed = diagnostics.report();
  const exposedCurrent = exposed.current.diagnostics[0];
  const exposedTransition = exposed.transitions.at(-1)?.diagnostics[0];
  if (exposedCurrent === undefined || exposedTransition === undefined) {
    throw new Error("Test diagnostic evidence is unavailable");
  }
  exposedCurrent.message = "mutated report";
  exposedTransition.source = { path: "other.html", line: 1, column: 1 };

  const retained = diagnostics.report();
  expect(retained.current.diagnostics[0]).toMatchObject({
    message: "The projected value is stale.",
    source: { path: "dashboard.html", line: 4, column: 2 },
  });
  expect(retained.transitions.at(-1)?.diagnostics[0]).toMatchObject({
    message: "The projected value is stale.",
    source: { path: "dashboard.html", line: 4, column: 2 },
  });
});

it("describes a degraded runtime without flattening its diagnostics", () => {
  expect(
    previewStatus("server", {
      phase: "degraded",
      diagnostics: [warning],
    }),
  ).toEqual({
    message: "Live with 1 warning",
    state: "warning",
    title: "The projected value is stale. Wait for the notebook to finish running.",
  });
});

it("queries owned runtime diagnostics through the preview deck", () => {
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    runtimes: ["server", "wasm"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: () => undefined,
    syncEditorQuery: async () => "accepted",
    navigate: () => undefined,
  });

  const report = deck.runtimeDiagnostics("server");
  expect(report?.current.phase).toBe("connecting");
  if (report !== undefined) {
    report.current.phase = "failed";
  }
  expect(deck.runtimeDiagnostics("server")?.current.phase).toBe("connecting");
  expect(deck.runtimeDiagnostics("unknown")).toBeUndefined();
  deck.dispose();
});

it("bounds history while keeping monotonic transition sequences", () => {
  const diagnostics = new RuntimeDiagnostics({
    runtime: "server",
    view: "dashboard",
    clock: () => 1_000,
    transitionLimit: 3,
  });

  for (let index = 0; index < 5; index += 1) {
    diagnostics.record({
      phase: index % 2 === 0 ? "synchronizing" : "ready",
      diagnostics: [],
    });
  }

  expect(diagnostics.report().transitions.map(({ sequence }) => sequence)).toEqual([3, 4, 5]);
});

it("records identity changes even when the runtime phase stays ready", () => {
  const diagnostics = new RuntimeDiagnostics({
    runtime: "server",
    view: "dashboard",
    clock: () => 1_000,
  });
  diagnostics.record({
    phase: "ready",
    diagnostics: [],
    revision: "revision-1",
    sessionId: "s_123456",
  });

  diagnostics.record({
    phase: "ready",
    diagnostics: [],
    revision: "revision-2",
    sessionId: "s_123456",
  });

  const report = diagnostics.report();
  expect(report.revision).toBe("revision-2");
  expect(report.transitions.map(({ revision }) => revision)).toEqual([
    null,
    "revision-1",
    "revision-2",
  ]);
});
