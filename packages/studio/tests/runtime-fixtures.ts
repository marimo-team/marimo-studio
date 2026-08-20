import type { RuntimeDescriptor } from "@marimo-studio/protocol/runtime-descriptor";

export const serverRuntime = {
  id: "server",
  label: "Server",
  description: "Uses the notebook kernel",
  execution: "kernel",
  projections: { cell: true, output: true, value: true },
  controls: "peer",
  query: "reactive",
  preparation: "primary",
  session: "shared",
} as const satisfies RuntimeDescriptor;

export const wasmRuntime = {
  id: "wasm",
  label: "WebAssembly",
  description: "Runs locally in your browser",
  execution: "worker",
  projections: { cell: true, output: true, value: true },
  controls: "state",
  query: "state",
  preparation: "after-primary",
  session: "isolated",
} as const satisfies RuntimeDescriptor;

export const zeroPythonRuntime = {
  id: "zero-python",
  label: "Zero-Python",
  description: "Loads prepared notebook states",
  execution: "prepared",
  projections: { cell: true, output: true, value: true },
  controls: "state",
  query: "state",
  preparation: "on-select",
  session: "none",
} as const satisfies RuntimeDescriptor;
