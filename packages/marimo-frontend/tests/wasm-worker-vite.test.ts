import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { afterEach, expect, test, vi } from "vite-plus/test";

import {
  exposeWasmRpcDeadline,
  isolateWasmWorker,
  launchInlineWorkerFromDataModule,
  usePresentationWasmController,
} from "../src/wasm-worker-vite.ts";
import {
  importModule,
  importTypeScriptFile,
  importTypeScriptModule,
  lineEndingVariants,
  temporaryDirectory,
} from "./transformed-modules.ts";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("opaque presentations execute through one owned inline WebAssembly worker", async () => {
  const readyListener = `this.rpc.addMessageListener("ready", () => {
      this.startSession();
    });`;
  const source = `
import workerUrl from "./worker/worker.ts?worker&url";
const saveWorkerUrl = "./worker/save-worker.ts";
const createModuleWorker = (url, options) => new Worker(url, { ...options, type: "module" });
const getWasmWorkerName = () => "presentation";
const getInitialAppMode = () => "read";
const userConfig = { runtime: { auto_instantiate: false } };
const getWorkerRPC = (worker, maxRequestTime) => ({
  worker,
  maxRequestTime,
  addMessageListener(_type, listener) { this.ready = listener; },
});
export class Bridge {
  startCalls = 0;
  startSession() { this.startCalls += 1; }
  mount() {
const main = createModuleWorker(new URL(workerUrl, import.meta.url), {
      // Pass the optional custom-controller capability to the worker.
      name: getWasmWorkerName(),
    });
const save = createModuleWorker(
      new URL(saveWorkerUrl, import.meta.url),
      {
        // Pass the optional custom-controller capability to the worker.
        name: getWasmWorkerName(),
      },
    );
const autoInstantiate = {
  auto_instantiate:
            getInitialAppMode() === "read"
              ? true
              : userConfig.runtime.auto_instantiate,
};
const worker = main;
this.rpc = getWorkerRPC<WorkerSchema>(worker);
${readyListener}
return { autoInstantiate, main, rpc: this.rpc, save };
  }
}`;

  const adapters = await temporaryDirectory("marimo-studio-worker-adapters-");
  const mainWorker = join(adapters, "main-worker.mjs");
  const owner = join(adapters, "owner.mjs");
  await writeFile(
    mainWorker,
    `export default class MainWorker {
  constructor(options) { this.kind = "inline-main"; this.options = options; }
}`,
  );
  await writeFile(
    owner,
    `export let starts = 0;
export const ownPresentationWasmWorker = (worker) => {
  worker.owned = true;
  return worker;
};
export const startPresentationWasmSession = (start) => {
  starts += 1;
  return start();
};`,
  );

  const transformed = lineEndingVariants(source).map((candidate) =>
    isolateWasmWorker(candidate, pathToFileURL(mainWorker).href, pathToFileURL(owner).href),
  );
  expect(transformed[0]).toBe(transformed[1]);
  vi.stubGlobal(
    "Worker",
    class {
      kind = "constructed-worker";
      options: WorkerOptions | undefined;
      url: URL | string;

      constructor(url: URL | string, options?: WorkerOptions) {
        this.options = options;
        this.url = url instanceof URL ? url : "data:text/javascript,inline-worker";
      }
    },
  );
  const module = await importTypeScriptFile(transformed[0]);
  const bridge = new module.Bridge();
  const mounted = bridge.mount();
  mounted.rpc.ready();

  expect(mounted.main).toMatchObject({
    kind: "constructed-worker",
    options: { name: "presentation", type: "module" },
    owned: true,
  });
  expect(mounted.save).toMatchObject({
    kind: "constructed-worker",
    options: { name: "presentation", type: "module" },
  });
  expect(mounted.save).not.toBe(mounted.main);
  expect(mounted.save.url).not.toBe(mounted.main.url);
  expect(mounted.main.url).toMatch(/^(?:blob|data):/);
  expect(mounted.save.url.protocol).toBe("file:");
  expect(mounted.save.url.pathname).toMatch(/\/worker\/save-worker\.ts$/);
  expect(mounted.rpc).toMatchObject({ maxRequestTime: 125_000, worker: mounted.main });
  expect(mounted.autoInstantiate.auto_instantiate).toBe(false);
  // The transformed fixture imports the owner adapter by this URL, so this
  // import reads the same module's live start count.
  expect((await import(pathToFileURL(owner).href)).starts).toBe(1);
  expect(bridge.startCalls).toBe(1);
  expect(() =>
    isolateWasmWorker(
      `${source}\nthis.rpc = getWorkerRPC<WorkerSchema>(worker);`,
      "/marimo/worker.ts",
      "/studio/wasm-worker-owner.ts",
    ),
  ).toThrow("Marimo WebAssembly workers no longer match the opaque-frame adapter");
  expect(() =>
    isolateWasmWorker(
      `${source}\n${readyListener}`,
      "/marimo/worker.ts",
      "/studio/wasm-worker-owner.ts",
    ),
  ).toThrow("Marimo WebAssembly workers no longer match the opaque-frame adapter");
});

test("presentation WebAssembly requests retain the startup window", async () => {
  const source = `export function getWorkerRPC<WorkerSchema extends RPCSchema>(worker: Worker) {
  return createRPC<ParentSchema, WorkerSchema>({
    transport: createWorkerTransport(worker, {
      transportId: TRANSPORT_ID,
    }),
    maxRequestTime: 20_000, // 20 seconds
  });
}
const TRANSPORT_ID = "transport";
const createWorkerTransport = (worker, options) => ({ worker, options });
const createRPC = (options) => options;`;
  const transformed = lineEndingVariants(source).map(exposeWasmRpcDeadline);

  expect(transformed[0]).toBe(transformed[1]);
  const module = await importTypeScriptModule(transformed[0]);
  expect(module.getWorkerRPC({}).maxRequestTime).toBe(20_000);
  expect(module.getWorkerRPC({}, 125_000).maxRequestTime).toBe(125_000);
  expect(() => exposeWasmRpcDeadline("export function getWorkerRPC() {}")).toThrow(
    "Marimo WebAssembly RPC deadline no longer matches the presentation adapter",
  );
  expect(() => exposeWasmRpcDeadline(`${source}\n${source}`)).toThrow(
    "Marimo WebAssembly RPC deadline no longer matches the presentation adapter",
  );
});

test("presentation workers use the in-memory controller", async () => {
  const adapter = `data:text/javascript,export const getController = () => "in-memory"`;
  const transformed = usePresentationWasmController(
    'import { getController } from "./getController";\nexport const controller = getController();',
    adapter,
  );

  expect((await importModule(transformed)).controller).toBe("in-memory");
});

test("Vite's self-contained worker payload launches as a data module", async () => {
  const transformed = launchInlineWorkerFromDataModule(`const jsContent = "worker";
const blob = new Blob([jsContent]);
export default function WorkerWrapper(options) {
  return new Worker(blob, { name: options?.name });
}`);
  vi.stubGlobal(
    "Worker",
    class {
      options: WorkerOptions | undefined;
      url: URL | string;

      constructor(url: URL | string, options?: WorkerOptions) {
        this.options = options;
        this.url = url;
      }
    },
  );
  const module = await importModule(transformed);
  const worker = module.default({ name: "presentation" });
  expect(worker.url).toBe("data:text/javascript;charset=utf-8,worker");
  expect(worker.options).toEqual({ type: "module", name: "presentation" });
});
