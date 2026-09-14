import { execFile } from "node:child_process";
import { access, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";
import { transformWithOxc } from "vite";
import { afterEach, expect, test } from "vite-plus/test";

import { decodeMarimoSource } from "../scripts/metadata.mjs";
import {
  assertCleanCheckout,
  assertMarimoCommit,
  expectedCommit,
  isPreparedOwnedCheckout,
  pnpmInvocation,
  prepareOwnedCheckout,
} from "../scripts/source.mjs";
import {
  classifyProjectedOutputFunctionErrors,
  evergreenKaTeXFontCss,
  extendWebSocketConnectionTimeout,
  scopeProjectedOutputFunctionRequests,
  silenceMissingPresentationCellScroll,
  stabilizeDataTableHeaderRefs,
} from "../src/vite.ts";
import {
  exposeWasmRpcDeadline,
  isolateWasmWorker,
  launchInlineWorkerFromDataModule,
  usePresentationWasmController,
} from "../src/wasm-worker-vite.ts";

const exec = promisify(execFile);
const temporaryPaths = [];

const temporaryDirectory = async (prefix) => {
  const path = await mkdtemp(join(tmpdir(), prefix));
  temporaryPaths.push(path);
  return path;
};

afterEach(async () => {
  await Promise.all(
    temporaryPaths.splice(0).map((path) =>
      rm(path, {
        force: true,
        maxRetries: 10,
        recursive: true,
        retryDelay: 20,
      }),
    ),
  );
});

const git = async (cwd, ...args) =>
  (
    await exec("git", args, {
      cwd,
      encoding: "utf8",
      env: { ...process.env, GIT_TRACE2_EVENT: "0" },
    })
  ).stdout.trim();

const createRepository = async (content) => {
  const path = await temporaryDirectory("marimo-studio-source-");
  await git(path, "init");
  await git(path, "config", "user.email", "studio@example.com");
  await git(path, "config", "user.name", "Marimo Studio");
  await writeFile(join(path, ".gitignore"), "node_modules/\npackages/llm-info/data/generated/\n");
  await writeFile(join(path, "tracked.txt"), content);
  await git(path, "add", ".gitignore", "tracked.txt");
  await git(path, "commit", "-m", "fixture");
  return { commit: await git(path, "rev-parse", "HEAD"), path };
};

const isMissing = async (path) => {
  try {
    await access(path);
    return false;
  } catch {
    return true;
  }
};

const lineEndingVariants = (source) => [source, source.replaceAll("\n", "\r\n")];

const importModule = async (source) =>
  import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

const compileTypeScript = async (source, loader = "ts") => {
  const transformed = await transformWithOxc(source, `fixture.${loader}`, {
    jsx: { pragma: "createElement", runtime: "classic" },
  });
  return transformed.code;
};

const importTypeScriptModule = async (source, loader = "ts") =>
  importModule(await compileTypeScript(source, loader));

const importTypeScriptFile = async (source) => {
  const directory = await temporaryDirectory("marimo-studio-transformed-module-");
  const path = join(directory, "fixture.mjs");
  await writeFile(path, await compileTypeScript(source));
  return import(pathToFileURL(path).href);
};

test("source metadata validates the prepared checkout contract", () => {
  expect(
    decodeMarimoSource(
      JSON.stringify({
        commit: "abc123",
        patchSha256: "a".repeat(64),
        path: "/tmp/marimo",
        repository: "https://github.com/marimo-team/marimo.git",
        version: "1.2.3",
        ignored: true,
      }),
    ),
  ).toEqual({
    commit: "abc123",
    patchSha256: "a".repeat(64),
    path: "/tmp/marimo",
    repository: "https://github.com/marimo-team/marimo.git",
    version: "1.2.3",
  });
  expect(() => decodeMarimoSource('{"commit":42}')).toThrow();
  expect(() => decodeMarimoSource("invalid")).toThrow();
});

test("package preparation invokes the workspace Corepack through Node", () => {
  const invocation = pnpmInvocation(["install", "--frozen-lockfile"]);
  expect(invocation.command).toBe(process.execPath);
  expect(invocation.args[0]).toMatch(/[/\\]corepack[/\\]dist[/\\]corepack\.js$/);
  expect(invocation.args.slice(1)).toEqual(["pnpm", "install", "--frozen-lockfile"]);

  expect(
    pnpmInvocation(["install", "--frozen-lockfile"], {
      nodeExecutable: "C:\\Program Files\\nodejs\\node.exe",
      corepackExecutable: "C:\\workspace\\node_modules\\corepack\\dist\\corepack.js",
    }),
  ).toEqual({
    command: "C:\\Program Files\\nodejs\\node.exe",
    args: [
      "C:\\workspace\\node_modules\\corepack\\dist\\corepack.js",
      "pnpm",
      "install",
      "--frozen-lockfile",
    ],
  });
});

test("the package exposes capability facades", async () => {
  const manifest = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));

  expect(new Set(Object.keys(manifest.exports))).toEqual(
    new Set([
      "./arrow-table",
      "./build-metadata",
      "./cell-presentation",
      "./control-endpoint",
      "./embedded-runtime",
      "./notebook-entry",
      "./prepared-presentation",
      "./projected-output",
      "./projected-output-function-gate",
      "./session-bootstrap",
      "./theme-frame",
      "./vite",
    ]),
  );
});

test("the evergreen browser build keeps one WOFF2 KaTeX source", () => {
  const css = evergreenKaTeXFontCss(`
@font-face {
  font-family: "KaTeX_Main";
  src:
    url("../fonts/KaTeX_Main-Regular.woff2") format("woff2"),
    url("../fonts/KaTeX_Main-Regular.woff") format("woff"),
    url("../fonts/KaTeX_Main-Regular.ttf") format("truetype");
}
`);

  expect(css).toContain('format("woff2")');
  expect(css).not.toContain('format("woff")');
  expect(css).not.toContain('format("truetype")');
});

test("the presentation table retains one observed header ref", async () => {
  const source = `
type Column<TData> = object;
type Table<TData> = object;
const TableHead = () => null;
const createElement = (_type, props) => ({ props });
let measurements = 0;
const columnSizingHandler = () => { measurements += 1; };
export const readMeasurements = () => measurements;
export function renderTableHeader<TData>(table: Table<TData>, header: { column: Column<TData> }) {
  return <TableHead
            ref={(thead) => {
              columnSizingHandler({ table, column: header.column, thead });
            }}
  />;
}
`;

  const transformed = lineEndingVariants(source).map(stabilizeDataTableHeaderRefs);
  expect(transformed[0]).toBe(transformed[1]);
  let disconnected = false;
  let observed;
  const previousResizeObserver = globalThis.ResizeObserver;
  globalThis.ResizeObserver = class {
    disconnect() {
      disconnected = true;
    }

    observe(element) {
      observed = element;
    }
  };
  try {
    const module = await importTypeScriptModule(transformed[0], "tsx");
    const table = {};
    const header = { column: {} };
    const first = module.renderTableHeader(table, header);
    const second = module.renderTableHeader(table, header);
    expect(first.props.ref).toBe(second.props.ref);

    const element = {};
    const release = first.props.ref(element);
    expect(module.readMeasurements()).toBe(1);
    expect(observed).toBe(element);
    release();
    expect(disconnected).toBe(true);
  } finally {
    globalThis.ResizeObserver = previousResizeObserver;
  }
});

test("presentation focus ignores native cell containers it does not render", async () => {
  const source = `
const warnings = [];
const Logger = { warn: (...args) => warnings.push(args) };
export const readWarnings = () => warnings;
export function scrollLegacyCellIntoView(element) {
  if (!element) {
    Logger.warn("scrollCellIntoView: element not found");
    return;
  }
}
export function scrollCellIntoView(element, cellId) {
  if (!element) {
    Logger.warn(
      \`[CellFocusManager] scrollCellIntoView: element not found: \${cellId}\`,
    );
  }
}
export function warnAboutOtherFailure() {
  Logger.warn("another focus failure");
}
`;

  const transformed = lineEndingVariants(source).map(silenceMissingPresentationCellScroll);
  expect(transformed[0]).toBe(transformed[1]);
  const module = await importModule(transformed[0]);
  module.scrollLegacyCellIntoView(null);
  module.scrollCellIntoView(null, "cell-1");
  module.warnAboutOtherFailure();
  expect(module.readWarnings()).toEqual([["another focus failure"]]);
});

test("browser connections retain the Studio startup window", () => {
  const source = `new ReconnectingWebSocket(urlProvider, undefined, {
      maxRetries: MAX_RETRIES,
      startClosed: true,
      connectionTimeout: 10_000,
    });`;

  const transformed = lineEndingVariants(source).map(extendWebSocketConnectionTimeout);
  expect(transformed[0]).toBe(transformed[1]);
  expect(transformed[0]).toContain("connectionTimeout: 30_000");
  expect(transformed[0]).not.toContain("connectionTimeout: 10_000");
  expect(() => extendWebSocketConnectionTimeout("connectionTimeout: 4_000,")).toThrow(
    "Marimo WebSocket connection timeout no longer matches the Studio adapter",
  );
});

test("projected plugin function calls carry their rendering host", () => {
  const source = `import { Provider } from "jotai";
async function invoke(hostElement, parsedArgs, key, namespace) {
          const response = await FUNCTIONS_REGISTRY.request({
            args: parsedArgs,
            functionName: key,
            namespace,
          });
  return response;
}`;

  const transformed = lineEndingVariants(source).map(scopeProjectedOutputFunctionRequests);
  expect(transformed[0]).toBe(transformed[1]);
  expect(transformed[0]).toContain(
    'import { runProjectedOutputFunctionRequest } from "marimo-studio:projected-output-function-gate";',
  );
  expect(transformed[0]).toContain("runProjectedOutputFunctionRequest(\n            hostElement,");
  expect(() => scopeProjectedOutputFunctionRequests('import { Provider } from "jotai";')).toThrow(
    "Marimo function requests no longer match the projected output adapter",
  );
  expect(() => scopeProjectedOutputFunctionRequests(`${source}\n${source}`)).toThrow(
    "Marimo function requests no longer match the projected output adapter",
  );
});

test("projected function cancellations bypass request error reporting", () => {
  const source = `import { useAtomValue } from "jotai";
async function request(keyString, handler, args) {
      try {
        return await handler(...args);
      } catch (error) {
        // Special handling for NoKernelConnectedError error
        report(error);
      }
}`;

  const transformed = lineEndingVariants(source).map(classifyProjectedOutputFunctionErrors);
  expect(transformed[0]).toBe(transformed[1]);
  expect(transformed[0]).toContain("classifyProjectedOutputFunctionRequest(operation)");
  expect(transformed[0]).toContain("if (isProjectedOutputFunctionAbort(error))");
  expect(() =>
    classifyProjectedOutputFunctionErrors('import { useAtomValue } from "jotai";'),
  ).toThrow("Marimo request errors no longer match the projected output adapter");
  expect(() => classifyProjectedOutputFunctionErrors(`${source}\n${source}`)).toThrow(
    "Marimo request errors no longer match the projected output adapter",
  );
});

test("opaque presentations execute through one owned inline WebAssembly worker", async () => {
  const readyListener = `this.rpc.addMessageListener("ready", () => {
      this.startSession();
    });`;
  const source = `
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
const main = new Worker(
      // oxlint-disable-next-line unicorn/relative-url-style
      new URL("./worker/worker.ts", import.meta.url),
      {
        type: "module",
        // Pass the version (and optional capability suffix) to the worker
        /* @vite-ignore */
        name: getWasmWorkerName(),
      },
    );
const save = new Worker(
      // oxlint-disable-next-line unicorn/relative-url-style
      new URL("./worker/save-worker.ts", import.meta.url),
      {
        type: "module",
        // Pass the version (and optional capability suffix) to the worker
        /* @vite-ignore */
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
    `export const ownPresentationWasmWorker = (worker) => {
  worker.owned = true;
  return worker;
};
export const startPresentationWasmSession = (start) => {
  globalThis.__MARIMO_STUDIO_TEST_WORKER_STARTS__ += 1;
  return start();
};`,
  );

  const transformed = lineEndingVariants(source).map((candidate) =>
    isolateWasmWorker(candidate, pathToFileURL(mainWorker).href, pathToFileURL(owner).href),
  );
  expect(transformed[0]).toBe(transformed[1]);
  const previousWorker = globalThis.Worker;
  globalThis.__MARIMO_STUDIO_TEST_WORKER_STARTS__ = 0;
  globalThis.Worker = class NativeWorker {
    constructor(url, options) {
      this.kind = "constructed-worker";
      this.options = options;
      this.url = url instanceof URL ? url : "data:text/javascript,inline-worker";
    }
  };
  try {
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
    expect(globalThis.__MARIMO_STUDIO_TEST_WORKER_STARTS__).toBe(1);
    expect(bridge.startCalls).toBe(1);
  } finally {
    globalThis.Worker = previousWorker;
    delete globalThis.__MARIMO_STUDIO_TEST_WORKER_STARTS__;
  }
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
  const previousWorker = globalThis.Worker;
  globalThis.Worker = class {
    constructor(url, options) {
      this.url = url;
      this.options = options;
    }
  };
  try {
    const module = await importModule(transformed);
    const worker = module.default({ name: "presentation" });
    expect(worker.url).toBe("data:text/javascript;charset=utf-8,worker");
    expect(worker.options).toEqual({ type: "module", name: "presentation" });
  } finally {
    globalThis.Worker = previousWorker;
  }
});

test("checkout preparation repairs ownership, dirt, and readiness", async () => {
  const expected = await createRepository("expected\n");
  const other = await createRepository("other\n");
  const checkout = await temporaryDirectory("marimo-studio-checkout-");
  const preparation = {
    path: checkout,
    repository: expected.path,
    commit: expected.commit,
  };

  await prepareOwnedCheckout({
    path: checkout,
    repository: other.path,
    commit: other.commit,
  });
  await prepareOwnedCheckout(preparation);

  expect(await git(checkout, "remote", "get-url", "origin")).toBe(expected.path);
  expect(await git(checkout, "rev-parse", "HEAD")).toBe(expected.commit);
  expect(await readFile(join(checkout, "tracked.txt"), "utf8")).toBe("expected\n");

  await writeFile(join(checkout, "tracked.txt"), "changed\n");
  await writeFile(join(checkout, "untracked.txt"), "changed\n");
  await prepareOwnedCheckout(preparation);

  expect(await readFile(join(checkout, "tracked.txt"), "utf8")).toBe("expected\n");
  expect(await isMissing(join(checkout, "untracked.txt"))).toBe(true);
  expect(await isPreparedOwnedCheckout(preparation)).toBe(false);

  await Promise.all([
    mkdir(join(checkout, "node_modules", ".pnpm"), { recursive: true }),
    mkdir(join(checkout, "frontend", "node_modules"), { recursive: true }),
    mkdir(join(checkout, "packages", "llm-info", "data", "generated"), {
      recursive: true,
    }),
  ]);
  await writeFile(
    join(checkout, "packages", "llm-info", "data", "generated", "models.json"),
    "{}\n",
  );

  expect(await isPreparedOwnedCheckout(preparation)).toBe(true);

  await writeFile(join(checkout, "untracked.ts"), "export {};\n");
  expect(await isPreparedOwnedCheckout(preparation)).toBe(false);
  await rm(join(checkout, "untracked.ts"));

  await writeFile(join(checkout, "tracked.txt"), "changed\n");
  expect(await isPreparedOwnedCheckout(preparation)).toBe(false);
}, 15_000);

test("an owned clone leaves its local source checkout unchanged", async () => {
  const source = await createRepository("source\n");
  const checkout = await temporaryDirectory("marimo-studio-local-clone-");

  await writeFile(join(source.path, "tracked.txt"), "next release\n");
  await git(source.path, "commit", "-am", "next release");
  await writeFile(join(source.path, "tracked.txt"), "local edit\n");
  await writeFile(join(source.path, "untracked.txt"), "local file\n");
  const sourceHead = await git(source.path, "rev-parse", "HEAD");
  const sourceStatus = await git(source.path, "status", "--porcelain=v1", "--untracked-files=all");

  await prepareOwnedCheckout({
    path: checkout,
    repository: source.path,
    commit: source.commit,
  });
  await writeFile(join(checkout, "tracked.txt"), "owned change\n");
  await prepareOwnedCheckout({
    path: checkout,
    repository: source.path,
    commit: source.commit,
  });

  expect(await git(source.path, "rev-parse", "HEAD")).toBe(sourceHead);
  expect(await git(source.path, "status", "--porcelain=v1", "--untracked-files=all")).toBe(
    sourceStatus,
  );
  expect(await readFile(join(source.path, "tracked.txt"), "utf8")).toBe("local edit\n");
  expect(await readFile(join(source.path, "untracked.txt"), "utf8")).toBe("local file\n");
  expect(await readFile(join(checkout, "tracked.txt"), "utf8")).toBe("source\n");
});

test("an owned checkout must match the pinned release commit", async () => {
  const source = await createRepository("release\n");
  await expect(assertMarimoCommit(source.path)).rejects.toThrow(expectedCommit);
});

test("patch preparation requires a clean owned checkout", async () => {
  const source = await createRepository("release\n");

  await assertCleanCheckout(source.path);
  await writeFile(join(source.path, "tracked.txt"), "changed\n");
  await expect(assertCleanCheckout(source.path)).rejects.toThrow("local source changes");

  await git(source.path, "checkout", "--", "tracked.txt");
  await writeFile(join(source.path, "untracked.ts"), "export {};\n");
  await expect(assertCleanCheckout(source.path)).rejects.toThrow("local source changes");
});

test("source acquisition rejects using the source as its owned checkout", async () => {
  const source = await createRepository("source\n");
  await expect(
    prepareOwnedCheckout({
      path: source.path,
      repository: source.path,
      commit: source.commit,
    }),
  ).rejects.toThrow("must be outside");
  expect(await readFile(join(source.path, "tracked.txt"), "utf8")).toBe("source\n");
});
