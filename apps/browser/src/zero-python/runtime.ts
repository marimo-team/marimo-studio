import type { PresentationRuntime } from "@marimo-studio/runtime";

import { definePresentationRuntime } from "@marimo-studio/runtime";

import type { ZeroPythonRuntimeDependencies } from "./composition.ts";

export const ZERO_PYTHON_RUNTIME_DESCRIPTOR = Object.freeze({
  id: "zero-python",
  label: "Zero-Python",
  description: "Loads prepared notebook states",
  execution: "prepared",
  projections: Object.freeze({ cell: true, output: true, value: true }),
  controls: "state",
  query: "state",
  preparation: "on-select",
  session: "none",
} as const);

export const createZeroPythonRuntime = (
  dependencies?: ZeroPythonRuntimeDependencies,
): PresentationRuntime =>
  definePresentationRuntime({
    descriptor: ZERO_PYTHON_RUNTIME_DESCRIPTOR,
    async mount(context, data) {
      const { mountZeroPythonRuntime } = await import("./mount.ts");
      context.signal.throwIfAborted();
      return mountZeroPythonRuntime(context, data, dependencies);
    },
  });

export const zeroPythonRuntime = createZeroPythonRuntime();
