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

import { createWasmValueReader, waitForWasmValueBridge } from "../values/wasm";
import { waitForWasmInitialization } from "./initialization";
import { mountSharedRuntime } from "./runtime";
import { hideRuntimeSelectionDuringStartup } from "./selection";

export interface WasmRuntimeData {
  code: string;
  filename: string;
  version: string;
}

const requestValues = (selectors: string[]) =>
  FUNCTIONS_REGISTRY.request({
    namespace: "_marimo_studio",
    functionName: "read_values",
    args: { selectors, max_value_bytes: 1_000_000 },
  });

const updateQuery = async (query: string): Promise<void> => {
  await FUNCTIONS_REGISTRY.request({
    namespace: "_marimo_studio",
    functionName: "sync_query",
    args: { query: notebookQueryValues(query) },
  });
};

export const mountWasmRuntime = (context: RuntimeContext, data: WasmRuntimeData): RuntimeSession =>
  mountSharedRuntime(context.presentation, context.root, {
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
      return waitForWasmInitialization(bridge.initialized.promise, (signal) =>
        waitForWasmValueBridge(requestValues, signal),
      ).finally(restoreRuntimeSelection);
    },
    updateQuery,
    valueReader: (_sessionId, initialized) => createWasmValueReader(initialized, requestValues),
  });
