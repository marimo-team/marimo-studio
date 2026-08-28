import type { EmbeddedCellExecutor } from "@marimo-studio/marimo-frontend/embedded-runtime";
import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";
import type { ValueReadRequest } from "@marimo-studio/protocol/value-read";
import type { RuntimeContext, RuntimeSession } from "@marimo-studio/runtime";

import { z } from "zod";

import type { RuntimeInvoke } from "./runtime";

import { reconcileOutputReadResponse } from "../outputs/reconcile";
import { createWasmOutputReader, createWasmOutputRequest } from "../outputs/wasm";
import { getRuntimeConfig } from "../runtime-config";
import {
  createWasmValueReader,
  functionResultSchema,
  throwIfWasmAborted,
  waitForWasmCaller,
  waitForWasmProjectionBridge,
} from "../values/wasm";
import { awaitWasmStartup, retryWasmRpc, WASM_PROJECTION_NAMESPACE } from "../wasm-rpc";
import { createWasmInitialization } from "./initialization";
import { mountSharedRuntime } from "./runtime";
import { type WasmRuntimeData, wasmRuntimeDataSchema } from "./wasm-config";
import { createWasmMountedProjectionPreparation } from "./wasm-mounted-projections";
import { createWasmProjectionExecutor } from "./wasm-projection-execution";
import { createWasmQueryWriter } from "./wasm-query";

const configureProjections = async (
  invoke: RuntimeInvoke,
  config: RuntimeConfig,
  generation: number,
  signal?: AbortSignal,
): Promise<void> => {
  const variables = Object.entries(config.projectionTargets.variables).flatMap(([name, target]) =>
    target.status === "ready" ? [name] : [],
  );
  const result = functionResultSchema.parse(
    await retryWasmRpc(
      () =>
        invoke({
          namespace: WASM_PROJECTION_NAMESPACE,
          functionName: "configure_projections",
          args: {
            revision: config.revision,
            generation,
            mounts: config.mounts,
            variables,
          },
        }),
      signal,
    ),
  );
  if (!result.found || result.status.code !== "ok") {
    throw new Error(result.status.message ?? "The projection bridge could not bind its revision.");
  }
  const configured = z
    .strictObject({
      revision: z.string().min(1),
      generation: z.int().nonnegative().max(Number.MAX_SAFE_INTEGER),
      applied: z.boolean(),
    })
    .parse(result.return_value);
  if (
    !configured.applied ||
    configured.revision !== config.revision ||
    configured.generation !== generation
  ) {
    throw new Error("A newer projection authorization superseded this runtime revision.");
  }
};

const requestValues = async (
  invoke: RuntimeInvoke,
  request: ValueReadRequest,
  signal?: AbortSignal,
) =>
  functionResultSchema.parse(
    await retryWasmRpc(
      () =>
        invoke({
          namespace: WASM_PROJECTION_NAMESPACE,
          functionName: "read_values",
          args: {
            revision: request.revision,
            projections: request.projections,
            active_projections: request.activeProjections,
            max_value_bytes: 1_000_000,
          },
        }),
      signal,
    ),
  );

const requestProjectionBridge = async (invoke: RuntimeInvoke, signal?: AbortSignal) =>
  functionResultSchema.parse(
    await retryWasmRpc(
      () =>
        invoke({
          namespace: WASM_PROJECTION_NAMESPACE,
          functionName: "projection_bridge_ready",
          args: {},
        }),
      signal,
    ),
  );

export const mountWasmRuntime = (
  context: RuntimeContext,
  initialData: WasmRuntimeData,
): RuntimeSession => {
  let data = initialData;
  let presentation = context.presentation;
  const initialization = createWasmInitialization();
  const queryWriter = createWasmQueryWriter(initialization.signal);
  let resolveProjectionRuntime = () => {};
  let rejectProjectionRuntime = (_cause: Error) => {};
  const projectionRuntimeReady = new Promise<void>((resolve, reject) => {
    resolveProjectionRuntime = resolve;
    rejectProjectionRuntime = reject;
  });
  let resolveCellExecutor = (_executeCells: EmbeddedCellExecutor) => {};
  let rejectCellExecutor = (_cause: Error) => {};
  const cellExecutorReady = new Promise<EmbeddedCellExecutor>((resolve, reject) => {
    resolveCellExecutor = resolve;
    rejectCellExecutor = reject;
  });
  const projectionExecutor = createWasmProjectionExecutor(
    async (cells) => (await cellExecutorReady)(cells),
    () => projectionRuntimeReady,
  );
  let authorizationGeneration = 0;
  let authorization:
    | {
        readonly projectionRevision: string;
        readonly revision: string;
        readonly generation: number;
        readonly promise: Promise<void>;
      }
    | undefined;
  const authorizeProjections = (
    invoke: RuntimeInvoke,
    config: RuntimeConfig,
    signal?: AbortSignal,
  ): Promise<void> => {
    let current = authorization;
    if (
      current?.projectionRevision !== config.projectionRevision ||
      current.revision !== config.revision
    ) {
      const generation = ++authorizationGeneration;
      let created:
        | {
            readonly projectionRevision: string;
            readonly revision: string;
            readonly generation: number;
            readonly promise: Promise<void>;
          }
        | undefined;
      let succeeded = false;
      throwIfWasmAborted(initialization.signal);
      const promise = configureProjections(invoke, config, generation, initialization.signal)
        .then(() => {
          succeeded = true;
        })
        .finally(() => {
          if (!succeeded && authorization === created) {
            authorization = undefined;
          }
        });
      created = {
        projectionRevision: config.projectionRevision,
        revision: config.revision,
        generation,
        promise,
      };
      current = created;
      authorization = created;
    }
    return waitForWasmCaller(current.promise, signal);
  };
  const runtime = mountSharedRuntime(context.presentation, context.root, {
    autoInstantiate: false,
    id: "wasm",
    instance: context.presentation.runtime.instance,
    initialMode: "read",
    viewMode: "read",
    exposeSession: false,
    transport: {
      kind: "wasm",
      autoInstantiate: false,
      code: data.code,
      filename: data.filename,
      version: data.version,
      url: new URL(context.presentation.rootUrl, globalThis.location.origin).toString(),
      waitForReady(workerInitialized, invoke, executeCells) {
        return awaitWasmStartup(
          initialization.wait(workerInitialized, async (signal) => {
            try {
              throwIfWasmAborted(signal);
              resolveCellExecutor(executeCells);
              const bootstrapCell = data.executionCells.find(
                (cell) => cell.id === data.bootstrapCellId,
              );
              if (bootstrapCell === undefined) {
                throw new Error("The WebAssembly projection bootstrap cell is unavailable.");
              }
              throwIfWasmAborted(signal);
              await waitForWasmCaller(executeCells([bootstrapCell]), signal);
              throwIfWasmAborted(signal);
              await waitForWasmProjectionBridge(
                (requestSignal) => requestProjectionBridge(invoke, requestSignal),
                signal,
              );
              throwIfWasmAborted(signal);
              await authorizeProjections(invoke, context.presentation, signal);
              throwIfWasmAborted(signal);
              resolveProjectionRuntime();
            } catch (cause) {
              const error =
                cause instanceof Error
                  ? cause
                  : new Error("The WebAssembly projection bridge failed to initialize.");
              rejectProjectionRuntime(error);
              throw error;
            }
          }),
        );
      },
    },
    updateQuery: (invoke, query) => queryWriter.write(invoke, query),
    valueReader: ({ initialized, invoke }) =>
      createWasmValueReader(
        async () => await initialized,
        async (request, signal) => {
          await waitForWasmCaller(projectionRuntimeReady, signal);
          const config = getRuntimeConfig();
          if (request.revision !== config.revision) {
            throw new Error("The value request revision is not active.");
          }
          await authorizeProjections(invoke, config, signal);
          await projectionExecutor.prepareRequests(config, data, request.projections, signal);
          return requestValues(invoke, request, signal);
        },
      ),
    outputReader: ({ initialized, invoke, sessionId }) =>
      createWasmOutputReader(
        async () => await initialized,
        createWasmOutputRequest(sessionId, invoke, async (request, signal) => {
          await waitForWasmCaller(projectionRuntimeReady, signal);
          const config = getRuntimeConfig();
          if (request.revision !== config.revision) {
            throw new Error("The output request revision is not active.");
          }
          await authorizeProjections(invoke, config, signal);
          await projectionExecutor.prepareRequests(config, data, request.projections, signal);
        }),
        reconcileOutputReadResponse,
      ),
  });
  const mountedProjections = createWasmMountedProjectionPreparation(
    presentation,
    data,
    projectionExecutor,
  );
  return {
    id: runtime.id,
    sessionId: runtime.sessionId,
    update(next) {
      const result = runtime.update(next);
      if (result === "applied") {
        data = wasmRuntimeDataSchema.parse(next.runtime.data);
        presentation = next;
        if (authorization?.projectionRevision !== next.projectionRevision) {
          authorization = undefined;
        }
        mountedProjections.update(presentation, data);
      }
      return result;
    },
    updateQuery: (query) => runtime.updateQuery(query),
    dispose: () => {
      const error = new DOMException("The runtime was disposed.", "AbortError");
      initialization.abort(error);
      queryWriter.dispose();
      mountedProjections.dispose();
      rejectCellExecutor(error);
      rejectProjectionRuntime(error);
      authorization = undefined;
      runtime.dispose();
    },
  };
};
