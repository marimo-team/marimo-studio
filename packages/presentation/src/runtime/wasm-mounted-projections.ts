import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import type { WasmRuntimeData } from "./wasm-config";
import type { WasmProjectionExecutor } from "./wasm-projection-execution";

import { projectionHosts } from "../projections/host-runtime";
import { mountedResolvedProjections } from "../projections/instances";

export interface WasmMountedProjectionPreparation {
  update(config: RuntimeConfig, data: WasmRuntimeData): void;
  dispose(): void;
}

export const createWasmMountedProjectionPreparation = (
  initialConfig: RuntimeConfig,
  initialData: WasmRuntimeData,
  executor: Pick<WasmProjectionExecutor, "prepare">,
): WasmMountedProjectionPreparation => {
  let config = initialConfig;
  let data = initialData;
  let identity = "";
  let controller: AbortController | undefined;

  const prepare = (): void => {
    const projections = mountedResolvedProjections(config);
    const nextIdentity = JSON.stringify([
      config.projectionRevision,
      ...projections.map((projection) => [
        projection.request.siteId,
        projection.request.instanceId,
        projection.request.kind,
        projection.request.target,
        projection.producer,
      ]),
    ]);
    if (nextIdentity === identity) {
      return;
    }
    identity = nextIdentity;
    controller?.abort();
    controller = undefined;
    if (projections.length === 0) {
      return;
    }
    const nextController = new AbortController();
    controller = nextController;
    void executor
      .prepare(config, data, projections, nextController.signal)
      .catch((cause: unknown) => {
        if (!nextController.signal.aborted) {
          console.error("Failed to execute a mounted WebAssembly projection.", cause);
        }
      });
  };

  const stop = projectionHosts.subscribe(prepare);
  prepare();
  return {
    update(nextConfig, nextData) {
      config = nextConfig;
      data = nextData;
      prepare();
    },
    dispose() {
      stop();
      controller?.abort();
      controller = undefined;
    },
  };
};
