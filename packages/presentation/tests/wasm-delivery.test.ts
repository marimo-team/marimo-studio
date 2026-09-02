import type { EmbeddedCellExecutor } from "@marimo-studio/marimo-frontend/embedded-runtime";
import type { JsonValue, RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import { afterEach, expect, test, vi } from "vite-plus/test";

import type { RuntimeInvoke } from "../src/runtime/runtime.tsx";
import type { WasmRuntimeData } from "../src/runtime/wasm-config.ts";

import { createWasmQueryWriter } from "../src/runtime/wasm-query.ts";
import {
  prepareWasmProjectionRuntime,
  resolveWasmRuntimeUrl,
} from "../src/runtime/wasm-startup.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

const data: WasmRuntimeData = {
  code: "",
  filename: "notebook.py",
  version: "1.0.0",
  executionCells: [{ id: "bootstrap-cell", code: "register_bridge()" }],
  bootstrapCellId: "bootstrap-cell",
};

const presentation = (): RuntimeConfig =>
  runtimeConfig({
    runtime: {
      id: "wasm",
      instance: "wasm-instance",
      data,
    },
    presentationSessionId: undefined,
  });

afterEach(() => {
  globalThis.history.replaceState({}, "", "/");
  vi.restoreAllMocks();
});

test.each([
  ["https://example.test/repository/site/pages/", "https://example.test/repository/site/"],
  ["https://example.test/moved/copy/pages/", "https://example.test/moved/copy/"],
])("resolves relative runtime resources after moving a nested export to %s", (baseUrl, rootUrl) => {
  expect(resolveWasmRuntimeUrl("../", baseUrl)).toBe(rootUrl);
});

test("synchronizes the canonical public query before authorizing projection execution", async () => {
  globalThis.history.replaceState(
    {},
    "",
    "/repository/site/pages/index.html?region=emea&region=apac&access_token=secret&runtime=wasm",
  );
  const config = presentation();
  const owner = new AbortController();
  const queryWriter = createWasmQueryWriter(owner.signal);
  const calls: string[] = [];
  const result = (returnValue: JsonValue) => ({
    found: true,
    status: { code: "ok", message: null },
    return_value: returnValue,
  });
  const invoke = vi.fn<RuntimeInvoke>(async (request) => {
    calls.push(request.functionName);
    if (request.functionName === "sync_query") {
      return result({
        generation: Number(request.args.generation),
        applied: true,
      });
    }
    return result(null);
  });
  const executeCells = vi.fn<EmbeddedCellExecutor>(async (cells) => {
    calls.push(`execute:${cells.map((cell) => cell.id).join(",")}`);
  });
  const authorizeProjections = vi.fn(async () => {
    calls.push("authorize");
  });

  await prepareWasmProjectionRuntime({
    authorizeProjections,
    config,
    data,
    executeCells,
    invoke,
    queryWriter,
    signal: owner.signal,
  });

  expect(calls).toEqual([
    "execute:bootstrap-cell",
    "projection_bridge_ready",
    "sync_query",
    "authorize",
  ]);
  expect(invoke).toHaveBeenCalledWith({
    namespace: "_marimo_studio_wasm",
    functionName: "sync_query",
    args: {
      query: { region: ["emea", "apac"] },
      generation: 1,
    },
  });
  expect(authorizeProjections).toHaveBeenCalledWith(invoke, config, owner.signal);
  queryWriter.dispose();
});
