import { afterEach, expect, test, vi } from "vite-plus/test";

import {
  classifyProjectedOutputFunctionErrors,
  evergreenKaTeXFontCss,
  extendWebSocketConnectionTimeout,
  scopeProjectedOutputFunctionRequests,
  silenceMissingPresentationCellScroll,
  stabilizeDataTableHeaderRefs,
} from "../src/vite.ts";
import {
  importModule,
  importModuleWithBindings,
  importTypeScriptModule,
  lineEndingVariants,
} from "./transformed-modules.ts";

afterEach(() => {
  vi.unstubAllGlobals();
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
  let observed: Element | undefined;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      disconnect() {
        disconnected = true;
      }

      observe(element: Element) {
        observed = element;
      }
    },
  );
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

test("browser connections retain the Studio startup window", async () => {
  const source = `export const connect = (ReconnectingWebSocket, urlProvider, MAX_RETRIES) =>
  new ReconnectingWebSocket(urlProvider, undefined, {
      maxRetries: MAX_RETRIES,
      startClosed: true,
      connectionTimeout: 10_000,
    });`;

  const transformed = lineEndingVariants(source).map(extendWebSocketConnectionTimeout);
  expect(transformed[0]).toBe(transformed[1]);
  const module = await importModule(transformed[0]);
  const socket = module.connect(
    class {
      constructor(
        _url: string,
        _protocols: undefined,
        readonly options: { connectionTimeout: number },
      ) {}
    },
    "ws://example.test",
    3,
  );
  expect(socket.options).toMatchObject({ maxRetries: 3, startClosed: true });
  expect(socket.options.connectionTimeout).toBeGreaterThan(10_000);
  expect(() => extendWebSocketConnectionTimeout("connectionTimeout: 4_000,")).toThrow();
});

test("projected plugin function calls carry their rendering host", async () => {
  const source = `import { Provider } from "jotai";
const FUNCTIONS_REGISTRY = { request: async (request) => request };
export async function invoke(hostElement, parsedArgs, key, namespace) {
          const response = await FUNCTIONS_REGISTRY.request({
            args: parsedArgs,
            functionName: key,
            namespace,
          });
  return response;
}`;

  const transformed = lineEndingVariants(source).map(scopeProjectedOutputFunctionRequests);
  expect(transformed[0]).toBe(transformed[1]);
  const runProjectedOutputFunctionRequest = vi.fn(
    <Result>(_host: { readonly id: string }, send: () => Promise<Result>) => send(),
  );
  const module = await importModuleWithBindings(transformed[0], {
    Provider: {},
    runProjectedOutputFunctionRequest,
  });
  const host = { id: "projected-table" };
  await expect(module.invoke(host, { value: 1 }, "lookup", "table")).resolves.toEqual({
    args: { value: 1 },
    functionName: "lookup",
    namespace: "table",
  });
  expect(runProjectedOutputFunctionRequest).toHaveBeenCalledOnce();
  expect(runProjectedOutputFunctionRequest).toHaveBeenCalledWith(host, expect.any(Function));
  expect(() => scopeProjectedOutputFunctionRequests('import { Provider } from "jotai";')).toThrow();
  expect(() => scopeProjectedOutputFunctionRequests(`${source}\n${source}`)).toThrow();
});

test("projected function cancellations bypass request error reporting", async () => {
  const source = `import { useAtomValue } from "jotai";
export const reported = [];
const report = (error) => reported.push(error);
export async function request(keyString, handler, args) {
      try {
        return await handler(...args);
      } catch (error) {
        // Special handling for NoKernelConnectedError error
        report(error);
      }
}`;

  const transformed = lineEndingVariants(source).map(classifyProjectedOutputFunctionErrors);
  expect(transformed[0]).toBe(transformed[1]);
  const abort = new Error("cancelled");
  const classifyProjectedOutputFunctionRequest = vi.fn(
    <Result>(operation: Promise<Result>) => operation,
  );
  const module = await importModuleWithBindings(transformed[0], {
    useAtomValue: () => undefined,
    classifyProjectedOutputFunctionRequest,
    isProjectedOutputFunctionAbort: (error: Error) => error === abort,
  });

  await expect(module.request("sendFunctionRequest", async () => "sent", [])).resolves.toBe("sent");
  await expect(module.request("sendStdin", async () => "stdin", [])).resolves.toBe("stdin");
  expect(classifyProjectedOutputFunctionRequest).toHaveBeenCalledOnce();
  await expect(module.request("sendFunctionRequest", () => Promise.reject(abort), [])).rejects.toBe(
    abort,
  );
  const failure = new Error("kernel failure");
  await module.request("sendFunctionRequest", () => Promise.reject(failure), []);
  expect(module.reported).toEqual([failure]);
  expect(() =>
    classifyProjectedOutputFunctionErrors('import { useAtomValue } from "jotai";'),
  ).toThrow();
  expect(() => classifyProjectedOutputFunctionErrors(`${source}\n${source}`)).toThrow();
});
