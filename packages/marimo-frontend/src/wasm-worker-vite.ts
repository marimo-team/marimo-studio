import type { Plugin } from "vite";

import { join } from "node:path";

const normalizeLineEndings = (source: string): string => source.replaceAll("\r\n", "\n");
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
const defaultWasmRpcFactory = `export function getWorkerRPC<WorkerSchema extends RPCSchema>(worker: Worker) {
  return createRPC<ParentSchema, WorkerSchema>({
    transport: createWorkerTransport(worker, {
      transportId: TRANSPORT_ID,
    }),
    maxRequestTime: 20_000, // 20 seconds`;
const configurableWasmRpcFactory = `export function getWorkerRPC<WorkerSchema extends RPCSchema>(
  worker: Worker,
  maxRequestTime = 20_000,
) {
  return createRPC<ParentSchema, WorkerSchema>({
    transport: createWorkerTransport(worker, {
      transportId: TRANSPORT_ID,
    }),
    maxRequestTime,`;
const defaultMainWorkerRpc = "this.rpc = getWorkerRPC<WorkerSchema>(worker);";
// Studio owns a 120-second terminal startup deadline and terminates this worker.
// Keep the transport deadline longer so package loading cannot fail first.
const extendedMainWorkerRpc = "this.rpc = getWorkerRPC<WorkerSchema>(worker, 125_000);";
const unownedSessionStart = `this.rpc.addMessageListener("ready", () => {
      this.startSession();
    });`;
const ownedSessionStart = `this.rpc.addMessageListener("ready", () => {
      startPresentationWasmSession(() => this.startSession());
    });`;

export const isolateWasmWorker = (
  source: string,
  mainWorker: string,
  workerOwner: string,
): string => {
  const normalized = normalizeLineEndings(source);
  if (
    !normalized.includes(mainWorkerSource) ||
    !normalized.includes(saveWorkerSource) ||
    normalized.split(defaultMainWorkerRpc).length !== 2 ||
    normalized.split(unownedSessionStart).length !== 2
  ) {
    throw new Error("Marimo WebAssembly workers no longer match the opaque-frame adapter");
  }
  if (!normalized.includes(forcedReadModeInstantiation)) {
    throw new Error("Marimo WebAssembly startup no longer matches selective presentation mode");
  }
  const imports = `import MarimoStudioMainWorker from ${JSON.stringify(`${mainWorker}?worker&inline`)};
import { ownPresentationWasmWorker, startPresentationWasmSession } from ${JSON.stringify(workerOwner)};
`;
  return (
    imports +
    normalized
      .replace(
        mainWorkerSource,
        "ownPresentationWasmWorker(new MarimoStudioMainWorker({ name: getWasmWorkerName() }))",
      )
      .replace(defaultMainWorkerRpc, extendedMainWorkerRpc)
      .replace(unownedSessionStart, ownedSessionStart)
      .replace(forcedReadModeInstantiation, selectiveReadModeInstantiation)
  );
};

export const exposeWasmRpcDeadline = (source: string): string => {
  const normalized = normalizeLineEndings(source);
  if (normalized.split(defaultWasmRpcFactory).length !== 2) {
    throw new Error("Marimo WebAssembly RPC deadline no longer matches the presentation adapter");
  }
  return normalized.replace(defaultWasmRpcFactory, configurableWasmRpcFactory);
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

const opaqueWasmWorker = (frontend: string, packageRoot: string): Plugin => {
  const workerRoot = join(frontend, "src", "core", "wasm", "worker");
  const workerOwner = join(packageRoot, "src", "wasm-worker-owner.ts").replaceAll("\\", "/");
  return {
    name: "marimo-studio-opaque-wasm-worker",
    enforce: "pre",
    transform(source, id) {
      const path = id.split("?", 1)[0]?.replaceAll("\\", "/");
      if (path?.endsWith("/core/wasm/bridge.ts")) {
        return {
          code: isolateWasmWorker(
            source,
            join(workerRoot, "worker.ts").replaceAll("\\", "/"),
            workerOwner,
          ),
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

const configurablePresentationWasmRpcDeadline = (frontend: string): Plugin => {
  const rpc = join(frontend, "src", "core", "wasm", "rpc.ts").replaceAll("\\", "/");
  return {
    name: "marimo-studio-presentation-wasm-rpc-deadline",
    enforce: "pre",
    transform(source, id) {
      const path = id.split("?", 1)[0]?.replaceAll("\\", "/");
      if (path === rpc) {
        return { code: exposeWasmRpcDeadline(source), map: null };
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
  plugins: [
    opaqueWasmWorker(frontend, packageRoot),
    configurablePresentationWasmRpcDeadline(frontend),
    inlineWasmWorkerDataModule(frontend),
  ],
  workerPlugins: () => [presentationWasmController(frontend, packageRoot)],
});
