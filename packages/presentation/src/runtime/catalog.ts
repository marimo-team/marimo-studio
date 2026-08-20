import { definePresentationRuntime, type PresentationRuntime } from "@marimo-studio/runtime";

import { serverRuntimeDataSchema } from "./server-config";
import { wasmRuntimeDataSchema } from "./wasm-config";

export const serverRuntime: PresentationRuntime = definePresentationRuntime({
  descriptor: {
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
  async mount(context, data) {
    const config = serverRuntimeDataSchema.parse(data);
    const { mountServerRuntime } = await import("./server");
    context.signal.throwIfAborted();
    return mountServerRuntime(context, config);
  },
});

export const wasmRuntime: PresentationRuntime = definePresentationRuntime({
  descriptor: {
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
  async mount(context, data) {
    const config = wasmRuntimeDataSchema.parse(data);
    const marker = document.createElement("marimo-wasm");
    marker.hidden = true;
    marker.setAttribute("aria-hidden", "true");
    document.body.append(marker);
    try {
      const { mountWasmRuntime } = await import("./wasm");
      context.signal.throwIfAborted();
      return mountWasmRuntime(context, config);
    } catch (error) {
      marker.remove();
      throw error;
    }
  },
});

export const presentationRuntimes = Object.freeze([serverRuntime, wasmRuntime]);
