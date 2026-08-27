import type { WasmController } from "@marimo-team/frontend/unstable_internal/core/wasm/worker/types";

import { DefaultWasmController } from "@marimo-team/frontend/unstable_internal/core/wasm/worker/bootstrap";
import { WasmFileSystem } from "@marimo-team/frontend/unstable_internal/core/wasm/worker/fs";

class PresentationWasmController extends DefaultWasmController {
  override async mountFilesystem(options: { code: string; filename: string | null }) {
    WasmFileSystem.createHomeDir(this.requirePyodide);
    return WasmFileSystem.initNotebookCode({
      pyodide: this.requirePyodide,
      code: options.code,
      filename: options.filename,
    });
  }
}

export const getController = async (_version: string): Promise<WasmController> =>
  new PresentationWasmController();
