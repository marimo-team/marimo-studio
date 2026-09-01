import type { Plugin } from "vite";

import { join } from "node:path";

const saveWorkerSource = `new Worker(
      // oxlint-disable-next-line unicorn/relative-url-style
      new URL("./worker/save-worker.ts", import.meta.url),
      {
        type: "module",
        // Pass the version (and optional capability suffix) to the worker
        /* @vite-ignore */
        name: getWasmWorkerName(),
      },
    )`;
const mainWorkerSource = `new Worker(
      // oxlint-disable-next-line unicorn/relative-url-style
      new URL("./worker/worker.ts", import.meta.url),
      {
        type: "module",
        // Pass the version (and optional capability suffix) to the worker
        /* @vite-ignore */
        name: getWasmWorkerName(),
      },
    )`;
const forcedReadModeInstantiation = `auto_instantiate:
            getInitialAppMode() === "read"
              ? true
              : userConfig.runtime.auto_instantiate,`;
const selectiveReadModeInstantiation = "auto_instantiate: userConfig.runtime.auto_instantiate,";

export const isolateWasmWorker = (source: string, mainWorker: string): string => {
  if (!source.includes(mainWorkerSource) || !source.includes(saveWorkerSource)) {
    throw new Error("Marimo WebAssembly workers no longer match the opaque-frame adapter");
  }
  if (!source.includes(forcedReadModeInstantiation)) {
    throw new Error("Marimo WebAssembly startup no longer matches selective presentation mode");
  }
  const imports = `import MarimoStudioMainWorker from ${JSON.stringify(`${mainWorker}?worker&inline`)};\n`;
  return (
    imports +
    source
      .replace(mainWorkerSource, "new MarimoStudioMainWorker({ name: getWasmWorkerName() })")
      .replace(forcedReadModeInstantiation, selectiveReadModeInstantiation)
  );
};

const defaultWasmControllerImport = 'import { getController } from "./getController";';

export const usePresentationWasmController = (source: string, adapter: string): string => {
  if (!source.includes(defaultWasmControllerImport)) {
    throw new Error(
      "Marimo WebAssembly controller import no longer matches the presentation adapter",
    );
  }
  return source.replace(
    defaultWasmControllerImport,
    `import { getController } from ${JSON.stringify(adapter)};`,
  );
};

export const launchInlineWorkerFromDataModule = (source: string): string => {
  const declarationStart = source.indexOf("const jsContent = ");
  const declarationEnd = source.indexOf(";\n", declarationStart);
  if (
    declarationStart !== 0 ||
    declarationEnd < 0 ||
    !source.includes("export default function WorkerWrapper")
  ) {
    throw new Error("Vite's inline worker wrapper no longer matches the data-module adapter");
  }
  const declaration = source.slice(0, declarationEnd + 1);
  return `${declaration}
export default function WorkerWrapper(options) {
  return new Worker(
    "data:text/javascript;charset=utf-8," + encodeURIComponent(jsContent),
    { type: "module", name: options?.name },
  );
}`;
};

const opaqueWasmWorker = (frontend: string): Plugin => {
  const workerRoot = join(frontend, "src", "core", "wasm", "worker");
  return {
    name: "marimo-studio-opaque-wasm-worker",
    enforce: "pre",
    transform(source, id) {
      const path = id.split("?", 1)[0]?.replaceAll("\\", "/");
      if (path?.endsWith("/core/wasm/bridge.ts")) {
        return {
          code: isolateWasmWorker(source, join(workerRoot, "worker.ts").replaceAll("\\", "/")),
          map: null,
        };
      }
    },
  };
};

const presentationWasmController = (frontend: string, packageRoot: string): Plugin => {
  const workerRoot = join(frontend, "src", "core", "wasm", "worker").replaceAll("\\", "/");
  const workers = new Set([`${workerRoot}/worker.ts`, `${workerRoot}/save-worker.ts`]);
  const controller = join(packageRoot, "src", "presentation-wasm-controller.ts").replaceAll(
    "\\",
    "/",
  );
  return {
    name: "marimo-studio-presentation-wasm-controller",
    enforce: "pre",
    transform(source, id) {
      const path = id.split("?", 1)[0]?.replaceAll("\\", "/");
      if (path && workers.has(path)) {
        return { code: usePresentationWasmController(source, controller), map: null };
      }
    },
  };
};

const inlineWasmWorkerDataModule = (frontend: string): Plugin => {
  const worker = join(frontend, "src", "core", "wasm", "worker", "worker.ts").replaceAll("\\", "/");
  return {
    name: "marimo-studio-inline-wasm-worker-data-module",
    enforce: "post",
    transform(source, id) {
      const [path, query = ""] = id.replaceAll("\\", "/").split("?", 2);
      if (
        path === worker &&
        query.split("&").includes("inline") &&
        source.trimStart().startsWith("const jsContent = ")
      ) {
        return { code: launchInlineWorkerFromDataModule(source), map: null };
      }
    },
  };
};

export const createWasmWorkerViteIntegration = (frontend: string, packageRoot: string) => ({
  plugins: [opaqueWasmWorker(frontend), inlineWasmWorkerDataModule(frontend)],
  workerPlugins: () => [presentationWasmController(frontend, packageRoot)],
});
