import type { PresentationRuntime } from "@marimo-studio/runtime";

import { definePresentationRuntime } from "@marimo-studio/runtime";

import type { ZeroPythonRuntimeDependencies } from "./composition.ts";

export const ZERO_PYTHON_RUNTIME_ID = "zero-python";

export const createZeroPythonRuntime = (
  dependencies?: ZeroPythonRuntimeDependencies,
): PresentationRuntime =>
  definePresentationRuntime({
    id: ZERO_PYTHON_RUNTIME_ID,
    async mount(context, data) {
      const { mountZeroPythonRuntime } = await import("./mount.ts");
      return mountZeroPythonRuntime(context, data, dependencies);
    },
  });

export const zeroPythonRuntime = createZeroPythonRuntime();
