import "./framed-document.ts";
import { previewMessageSchema } from "@marimo-studio/protocol/preview-messages";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { projectionHosts } from "../src/projections/host-runtime.ts";
import {
  setRuntimeConnectionState,
  startRenderedViewObserver,
  stopRenderedViewObserver,
} from "../src/rendered-view-observer.ts";
import { renderedViewIdentity } from "../src/rendered-view-state.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { markValueError } from "../src/values/hosts.ts";
import { projectionRequest, projectionRuntimeConfig, runtimeConfig } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "wasm",
  runtimeExplicit: true,
  replay: false,
};

afterEach(() => {
  stopRenderedViewObserver();
  projectionHosts.disconnect();
  document.body.replaceChildren();
  globalThis.__MARIMO_STUDIO_SESSION_ID__ = undefined;
  vi.restoreAllMocks();
});

test("WASM evidence omits forged native session identity", () => {
  globalThis.__MARIMO_STUDIO_SESSION_ID__ = "s_forged";

  expect(renderedViewIdentity()).toMatchObject({ runtime: "wasm" });
  expect(renderedViewIdentity().sessionId).toBeUndefined();

  commitRuntimeConfig(
    runtimeConfig({
      runtime: {
        id: "wasm",
        instance: "wasm-instance",
        data: {},
      },
    }),
  );
  expect(renderedViewIdentity()).toMatchObject({ runtime: "wasm" });
  expect(renderedViewIdentity().sessionId).toBeUndefined();
});

test("WASM committed errors attest an explicit sessionless identity", async () => {
  const config = projectionRuntimeConfig([projectionRequest("summary.total", "value")]);
  commitRuntimeConfig({
    ...config,
    runtime: {
      id: "wasm",
      instance: "wasm-instance",
      data: {},
    },
  });
  document.body.innerHTML = `
    <span
      mo-value="summary.total"
      data-marimo-studio-site="site:value:summary.total"
    ></span>
  `;
  projectionHosts.connect();
  markValueError(
    "summary.total",
    {
      code: "missing-variable",
      message: "summary is unavailable.",
      hint: "Restore summary in the notebook.",
    },
    config.projectionRevision,
  );
  const postMessage = vi.spyOn(globalThis.parent, "postMessage");
  startRenderedViewObserver(async () => {});
  setRuntimeConnectionState("ready");
  await new Promise((resolve) => setTimeout(resolve, 0));

  const terminal = postMessage.mock.calls.flatMap(([message]) => {
    const payload = jsonValueSchema.safeParse(message);
    if (!payload.success) {
      return [];
    }
    const parsed = previewMessageSchema.parse(payload.data);
    return parsed.type === "marimo-studio:view-error" ? [parsed] : [];
  })[0];
  expect(terminal).toMatchObject({
    type: "marimo-studio:view-error",
    revision: "presentation-revision",
    sessionId: null,
    diagnostic: { code: "missing-variable", target: "summary.total" },
  });
});
