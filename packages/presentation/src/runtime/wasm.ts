import type { RuntimeContext, RuntimeSession } from "@marimo-studio/runtime";

import { notebookQueryValues } from "@marimo-studio/protocol/query";

import type { RuntimeInvoke } from "./runtime";

import { reconcileOutputReadResponse } from "../outputs/reconcile";
import { createWasmOutputReader, createWasmOutputRequest } from "../outputs/wasm";
import {
  createWasmValueReader,
  functionResultSchema,
  waitForWasmValueBridge,
} from "../values/wasm";
import { awaitWasmStartup, retryWasmRpc } from "../wasm-rpc";
import { waitForWasmInitialization } from "./initialization";
import { mountSharedRuntime } from "./runtime";
import { hideRuntimeSelectionDuringStartup } from "./selection";
import {
  createProjectionSpecSynchronizer,
  type WasmProjectionSpecs,
  type WasmRuntimeData,
  wasmRuntimeDataSchema,
} from "./wasm-config";

const requestValues = async (invoke: RuntimeInvoke, selectors: string[], signal?: AbortSignal) =>
  functionResultSchema.parse(
    await retryWasmRpc(
      () =>
        invoke({
          namespace: "_marimo_studio",
          functionName: "read_values",
          args: { selectors, max_value_bytes: 1_000_000 },
        }),
      signal,
    ),
  );

const updateQuery = async (invoke: RuntimeInvoke, query: string): Promise<void> => {
  await retryWasmRpc(() =>
    invoke({
      namespace: "_marimo_studio",
      functionName: "sync_query",
      args: { query: notebookQueryValues(query) },
    }),
  );
};

export const mountWasmRuntime = (
  context: RuntimeContext,
  initialData: WasmRuntimeData,
): RuntimeSession => {
  let data = initialData;
  let ensureProjectionSpecs: ((specs: WasmProjectionSpecs) => Promise<void>) | undefined;
  const projectionSpecs = (invoke: RuntimeInvoke) => {
    ensureProjectionSpecs ??= createProjectionSpecSynchronizer(
      initialData,
      async ({ outputSpecs, valueSpecs }) => {
        const result = functionResultSchema.parse(
          await retryWasmRpc(() =>
            invoke({
              namespace: "_marimo_studio",
              functionName: "sync_projection_specs",
              args: {
                value_specs: valueSpecs,
                output_specs: outputSpecs,
              },
            }),
          ),
        );
        if (!result.found) {
          throw new Error("The notebook projection bridge is unavailable.");
        }
        if (result.status.code !== "ok") {
          throw new Error(result.status.message ?? "The notebook projection bridge failed.");
        }
      },
    );
    return ensureProjectionSpecs;
  };

  const runtime = mountSharedRuntime(context.presentation, context.root, {
    id: "wasm",
    instance: context.presentation.runtime.instance,
    initialMode: "read",
    viewMode: "read",
    exposeSession: false,
    transport: {
      kind: "wasm",
      code: data.code,
      filename: data.filename,
      version: data.version,
      url: new URL(context.presentation.rootUrl, globalThis.location.origin).toString(),
      waitForReady(workerInitialized, invoke) {
        const restoreRuntimeSelection = hideRuntimeSelectionDuringStartup();
        return awaitWasmStartup(
          waitForWasmInitialization(workerInitialized, (signal) =>
            waitForWasmValueBridge(
              (selectors, requestSignal) => requestValues(invoke, selectors, requestSignal),
              signal,
            ),
          ),
        ).finally(restoreRuntimeSelection);
      },
    },
    updateQuery,
    valueReader: ({ initialized, invoke }) =>
      createWasmValueReader(
        async () => {
          await initialized;
          await projectionSpecs(invoke)(data);
        },
        (selectors, signal) => requestValues(invoke, selectors, signal),
      ),
    outputReader: ({ initialized, invoke, sessionId }) =>
      createWasmOutputReader(
        async () => {
          await initialized;
          await projectionSpecs(invoke)(data);
        },
        createWasmOutputRequest(sessionId, invoke),
        reconcileOutputReadResponse,
      ),
  });
  return {
    id: runtime.id,
    sessionId: runtime.sessionId,
    update(next) {
      const result = runtime.update(next);
      if (result === "applied") {
        data = wasmRuntimeDataSchema.parse(next.runtime.data);
      }
      return result;
    },
    updateQuery: (query) => runtime.updateQuery(query),
    dispose: () => runtime.dispose(),
  };
};
