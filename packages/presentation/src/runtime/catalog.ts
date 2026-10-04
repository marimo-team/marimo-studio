import { definePresentationRuntime, type PresentationRuntime } from "@marimo-studio/runtime";

import { parseServerRuntime } from "./server-config";
import { parseWasmRuntime } from "./wasm-config";

export const serverRuntime: PresentationRuntime = definePresentationRuntime({
  id: "server",
  async mount(context) {
    const runtime = parseServerRuntime(context.presentation.runtime);
    const { mountServerRuntime } = await import("./server");
    return mountServerRuntime(context, runtime);
  },
});

export const wasmRuntime: PresentationRuntime = definePresentationRuntime({
  id: "wasm",
  async mount(context) {
    const config = parseWasmRuntime(context.presentation.runtime);
    const marker = document.createElement("marimo-wasm");
    marker.hidden = true;
    marker.setAttribute("aria-hidden", "true");
    document.body.append(marker);
    const { mountWasmRuntime } = await import("./wasm");
    return mountWasmRuntime(context, config);
  },
});
