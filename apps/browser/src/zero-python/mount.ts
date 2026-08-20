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
import { ZERO_PYTHON_RUNTIME_DESCRIPTOR } from "./runtime.ts";

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
  const controller = new ZeroPythonRuntimeController(
    parseZeroPythonRuntimeData(data),
    context.presentation,
    context.root,
    dependencies,
    (instance) => context.commitRuntimeInstance(instance),
  );
  try {
    await controller.start(context.signal);
  } catch (error) {
    await controller.dispose().catch(() => {});
    throw error;
  }
  return {
    id: ZERO_PYTHON_RUNTIME_DESCRIPTOR.id,
    initialQueryApplied: true,
    updateQuery: (query, signal) => controller.updateQuery(query, signal),
    beginRevision: async (signal) => {
      const revision = await controller.beginRevision(signal);
      return {
        async apply(next) {
          if (next.runtime.descriptor.id !== ZERO_PYTHON_RUNTIME_DESCRIPTOR.id) {
            return "reload";
          }
          return await revision.apply(next, parseZeroPythonRuntimeData(next.runtime.data));
        },
        commit: () => revision.commit(),
        rollback: () => revision.rollback(),
      };
    },
    dispose: () => controller.dispose(),
  };
};
