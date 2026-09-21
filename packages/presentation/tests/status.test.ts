import { afterEach, expect, test, vi } from "vite-plus/test";

import { clearDiagnostic, showDiagnostic } from "../src/document/status.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
};

afterEach(() => {
  document.body.replaceChildren();
  globalThis.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});

test("pre-config diagnostics use the server-minted mount runtime", () => {
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  globalThis.history.replaceState({}, "", "/dashboard/?runtime=wasm");

  showDiagnostic({
    scope: "presentation",
    code: "presentation-waiting",
    severity: "warning",
    message: "The presentation is waiting.",
    hint: "",
    view: "dashboard",
  });

  expect(parent.postMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "marimo-studio:view-error",
      runtime: "server",
    }),
    globalThis.location.origin,
  );
});

test("a direct wrapper shows its waiting diagnostic", () => {
  commitRuntimeConfig(runtimeConfig());
  vi.stubGlobal("parent", { postMessage: vi.fn() });
  const diagnostic = {
    scope: "presentation" as const,
    code: "presentation-waiting",
    severity: "warning" as const,
    message: "The presentation is waiting.",
    hint: "Wait for the current build.",
    view: "dashboard",
  };

  globalThis.history.replaceState({}, "", "/dashboard/");
  showDiagnostic(diagnostic, "waiting");
  const host = document.querySelector<HTMLElement>("[data-marimo-studio-diagnostic]")!;
  expect(host.hidden).toBe(false);
  expect(host.getAttribute("role")).toBe("status");
  expect(host.textContent).toBe(diagnostic.message);
});

test("unchanged diagnostic publications notify the parent once until cleared", () => {
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  const diagnostic = {
    scope: "presentation" as const,
    code: "development-disconnected",
    severity: "warning" as const,
    message: "Live updates disconnected.",
    hint: "Reconnect the server.",
    view: "dashboard",
    source: { path: "src/App.tsx", line: 12, column: 3 },
  };
  showDiagnostic(diagnostic, "waiting");
  showDiagnostic({ ...diagnostic }, "waiting");
  expect(parent.postMessage).toHaveBeenCalledOnce();
  expect(parent.postMessage).toHaveBeenLastCalledWith(
    expect.objectContaining({ diagnostic: expect.objectContaining({ source: diagnostic.source }) }),
    globalThis.location.origin,
  );
  clearDiagnostic();
  showDiagnostic(diagnostic, "waiting");
  expect(parent.postMessage).toHaveBeenCalledTimes(2);
});
