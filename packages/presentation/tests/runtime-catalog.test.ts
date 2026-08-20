import { createRuntimeRegistry } from "@marimo-studio/runtime";
import { expect, test } from "vite-plus/test";

import { presentationRuntimes, serverRuntime, wasmRuntime } from "../src/runtime/catalog.ts";

test("browser composition declares the Server and WebAssembly capabilities", () => {
  expect(presentationRuntimes.map((runtime) => runtime.descriptor)).toEqual([
    {
      id: "server",
      label: "Server",
      description: "Uses the notebook kernel",
      execution: "kernel",
      projections: { cell: true, output: true, value: true },
      controls: "peer",
      query: "reactive",
      preparation: "primary",
      session: "shared",
    },
    {
      id: "wasm",
      label: "WebAssembly",
      description: "Runs locally in your browser",
      execution: "worker",
      projections: { cell: true, output: true, value: true },
      controls: "state",
      query: "state",
      preparation: "after-primary",
      session: "isolated",
    },
  ]);

  const registry = createRuntimeRegistry(presentationRuntimes);
  expect(registry.resolve(serverRuntime.descriptor).descriptor).toEqual(serverRuntime.descriptor);
  expect(registry.resolve(wasmRuntime.descriptor).descriptor).toEqual(wasmRuntime.descriptor);
});
