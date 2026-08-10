import type { RuntimeContext, RuntimeSession } from "@marimo-studio/runtime";

import {
  codeAtom,
  filenameAtom,
  FUNCTIONS_REGISTRY,
  marimoVersionAtom,
  PyodideBridge,
  requestClientAtom,
  resolveRequestClient,
  runtimeConfigAtom,
  store,
} from "@marimo-studio/marimo-frontend/runtime";
import { notebookQueryValues } from "@marimo-studio/protocol/query";

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
  type WasmRuntimeData,
  wasmRuntimeDataSchema,
} from "./wasm-config";

const requestValues = (selectors: string[], signal?: AbortSignal) =>
  retryWasmRpc(
    () =>
      FUNCTIONS_REGISTRY.request({
        namespace: "_marimo_studio",
        functionName: "read_values",
        args: { selectors, max_value_bytes: 1_000_000 },
      }),
    signal,
  );

const updateQuery = async (query: string): Promise<void> => {
  await retryWasmRpc(() =>
    FUNCTIONS_REGISTRY.request({
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
  const ensureProjectionSpecs = createProjectionSpecSynchronizer(
    initialData,
    async ({ outputSpecs, valueSpecs }) => {
      const result = functionResultSchema.parse(
        await retryWasmRpc(() =>
          FUNCTIONS_REGISTRY.request({
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
  const runtime = mountSharedRuntime(context.presentation, context.root, {
    id: "wasm",
    instance: context.presentation.runtime.instance,
    initialMode: "read",
    viewMode: "read",
    exposeSession: false,
    configureTransport() {
      store.set(codeAtom, data.code);
      store.set(filenameAtom, data.filename);
      store.set(marimoVersionAtom, data.version);
      store.set(runtimeConfigAtom, {
        url: new URL(context.presentation.rootUrl, globalThis.location.origin).toString(),
        lazy: false,
        serverToken: "",
      });
      const restoreRuntimeSelection = hideRuntimeSelectionDuringStartup();
      const bridge = PyodideBridge.INSTANCE;
      store.set(requestClientAtom, resolveRequestClient());
      return awaitWasmStartup(
        waitForWasmInitialization(bridge.initialized.promise, (signal) =>
          waitForWasmValueBridge(requestValues, signal),
        ),
      ).finally(restoreRuntimeSelection);
    },
    updateQuery,
    valueReader: (_sessionId, initialized) =>
      createWasmValueReader(async () => {
        await initialized;
        await ensureProjectionSpecs(data);
      }, requestValues),
    outputReader: (sessionId, initialized) =>
      createWasmOutputReader(
        async () => {
          await initialized;
          await ensureProjectionSpecs(data);
        },
        createWasmOutputRequest(sessionId, (request) => FUNCTIONS_REGISTRY.request(request)),
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
