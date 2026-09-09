import type { RuntimeContext, RuntimeData, RuntimeSession } from "@marimo-studio/runtime";

import {
  mountPreparedProjections,
  presentationThemeSource,
} from "@marimo-studio/presentation/prepared-projections";
import { setRuntimeConnectionState } from "@marimo-studio/presentation/runtime-state";

import type { ZeroPythonRuntimeDependencies } from "./composition.ts";

import { ZeroPythonRuntimeController } from "./controller.ts";
import { parseZeroPythonRuntimeData } from "./metadata.ts";
import { createZeroPythonProjectionLoaders } from "./projections.ts";
import { ZERO_PYTHON_RUNTIME_ID } from "./runtime.ts";

const defaultDependencies = (): ZeroPythonRuntimeDependencies => ({
  loaders: createZeroPythonProjectionLoaders(),
  mountProjections: mountPreparedProjections,
  theme: presentationThemeSource,
  setConnectionState: setRuntimeConnectionState,
});

export const mountZeroPythonRuntime = async (
  context: RuntimeContext,
  data: RuntimeData,
  dependencies: ZeroPythonRuntimeDependencies = defaultDependencies(),
): Promise<RuntimeSession> => {
  const lifetime = new AbortController();
  const controller = new ZeroPythonRuntimeController(
    parseZeroPythonRuntimeData(data),
    context.presentation,
    context.root,
    dependencies,
  );
  try {
    await controller.start(lifetime.signal);
  } catch (error) {
    await controller.dispose().catch(() => {});
    throw error;
  }
  return {
    id: ZERO_PYTHON_RUNTIME_ID,
    update(next) {
      return next.runtime.id === ZERO_PYTHON_RUNTIME_ID &&
        next.runtime.instance === context.presentation.runtime.instance
        ? "applied"
        : "reload";
    },
    updateQuery: (query) => controller.updateQuery(query, lifetime.signal),
    async dispose() {
      lifetime.abort(new DOMException("Prepared runtime disposed", "AbortError"));
      await controller.dispose();
    },
  };
};
