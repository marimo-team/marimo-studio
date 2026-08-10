import { definePresentationRuntime, type PresentationRuntime } from "@marimo-studio/runtime";
import { z } from "zod";

import { wasmRuntimeDataSchema } from "./wasm-config";

const serverDataSchema = z.object({
  url: z.string(),
  serverToken: z.string(),
  fileKey: z.string(),
  file: z.string().optional(),
  preserveSession: z.boolean(),
});

export const serverRuntime: PresentationRuntime = definePresentationRuntime({
  id: "server",
  async mount(context, data) {
    const config = serverDataSchema.parse(data);
    const { mountServerRuntime } = await import("./server");
    return mountServerRuntime(context, config);
  },
});

export const wasmRuntime: PresentationRuntime = definePresentationRuntime({
  id: "wasm",
  async mount(context, data) {
    const config = wasmRuntimeDataSchema.parse(data);
    const marker = document.createElement("marimo-wasm");
    marker.hidden = true;
    marker.setAttribute("aria-hidden", "true");
    document.body.append(marker);
    const { mountWasmRuntime } = await import("./wasm");
    return mountWasmRuntime(context, config);
  },
});
