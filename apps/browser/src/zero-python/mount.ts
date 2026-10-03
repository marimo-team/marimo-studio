import type { RuntimeContext, RuntimeSession } from "@marimo-studio/runtime";

import {
  mountPreparedProjections,
  presentationThemeSource,
} from "@marimo-studio/presentation/prepared-projections";
import { setRuntimeConnectionState } from "@marimo-studio/presentation/runtime-state";

import type { ZeroPythonRuntimeDependencies } from "./composition.ts";

import { ZeroPythonRuntimeController } from "./controller.ts";
import { zeroPythonFailure } from "./errors.ts";
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
  dependencies: ZeroPythonRuntimeDependencies = defaultDependencies(),
): Promise<RuntimeSession> => {
  const lifetime = new AbortController();
  const controller = new ZeroPythonRuntimeController(
    parseZeroPythonRuntimeData(context.presentation.runtime),
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
  const replace = async (
    next: RuntimeContext["presentation"],
    data: ReturnType<typeof parseZeroPythonRuntimeData>,
  ) => {
    try {
      await controller.replace(next, data, lifetime.signal);
    } catch (error) {
      if (!lifetime.signal.aborted) {
        const failure = zeroPythonFailure(error);
        dependencies.setConnectionState("error", {
          code: failure.code,
          message: failure.message,
          hint: "Reload this view to open the current Prepared publication.",
        });
      }
    }
  };
  return {
    id: ZERO_PYTHON_RUNTIME_ID,
    update(next) {
      if (
        next.runtime.id !== ZERO_PYTHON_RUNTIME_ID ||
        next.runtime.instance !== context.presentation.runtime.instance
      ) {
        return "reload";
      }
      let data: ReturnType<typeof parseZeroPythonRuntimeData>;
      try {
        data = parseZeroPythonRuntimeData(next.runtime);
      } catch {
        // A reload mounts the configuration again and reports its error.
        return "reload";
      }
      if (data.manifestUrl !== controller.manifestUrl) {
        void replace(next, data);
      }
      return "applied";
    },
    updateQuery: (query) => controller.updateQuery(query, lifetime.signal),
    async dispose() {
      lifetime.abort(new DOMException("Prepared runtime disposed", "AbortError"));
      await controller.dispose();
    },
  };
};
