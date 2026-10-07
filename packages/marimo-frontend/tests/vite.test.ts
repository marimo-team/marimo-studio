import { afterEach, expect, test, vi } from "vite-plus/test";

import {
  classifyProjectedOutputFunctionErrors,
  evergreenKaTeXFontCss,
  extendWebSocketConnectionTimeout,
  scopeProjectedOutputFunctionRequests,
  silenceMissingPresentationCellScroll,
  stabilizeDataTableHeaderRefs,
} from "../src/vite.ts";
import { importModule, importTypeScriptModule, lineEndingVariants } from "./transformed-modules.ts";

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
