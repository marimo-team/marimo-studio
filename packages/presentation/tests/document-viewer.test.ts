import type { JsonValue } from "@marimo-studio/protocol/runtime-config";

import { afterEach, beforeAll, beforeEach, expect, test, vi } from "vite-plus/test";

import { registerMarimoDocumentElement } from "../src/documents/viewer.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

const SVG = '<svg xmlns="http://www.w3.org/2000/svg"></svg>';

interface RenderCall {
  readonly url: string;
  readonly body: unknown;
}

const svg = () => new Response(SVG, { headers: { "Content-Type": "image/svg+xml" } });

const failure = (status: number, body: JsonValue) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

// Value runtimes define a `marimoValue` getter on each settled host. The test
// stands in for that runtime so the element sees browser-computed values.
const settle = (host: HTMLElement, value: JsonValue): void => {
  Object.defineProperty(host, "marimoValue", { configurable: true, get: () => value });
  host.dataset.state = "ready";
  host.dispatchEvent(new CustomEvent("marimo-value-updated", { bubbles: true, composed: true }));
};

const mount = () => {
  document.body.innerHTML = `
    <main id="app-shell">
      <marimo-document src="card.svg" type="image/svg+xml" render>
        <span hidden mo-value="total"></span>
      </marimo-document>
    </main>
  `;
  const viewer = document.querySelector<HTMLElement>("marimo-document");
  const host = document.querySelector<HTMLElement>("[mo-value]");
  if (!viewer || !host) {
    throw new Error("The document fixture did not mount");
  }
  return { viewer, host };
};

const shadow = (viewer: HTMLElement): ShadowRoot => {
  if (!viewer.shadowRoot) {
    throw new Error("The document viewer has no shadow root");
  }
  return viewer.shadowRoot;
};

let calls: RenderCall[] = [];
let objectUrls = 0;

beforeAll(() => {
  registerMarimoDocumentElement();
  URL.createObjectURL = () => {
    objectUrls += 1;
    return "blob:document";
  };
  URL.revokeObjectURL = () => {};
  HTMLImageElement.prototype.decode = () => Promise.resolve();
});

beforeEach(() => {
  vi.useFakeTimers();
  // The page runtime installs this API. Only prepared exports have a state.
  vi.stubGlobal("marimoStudio", {});
  calls = [];
  objectUrls = 0;
  commitRuntimeConfig(
    runtimeConfig({ runtime: { id: "wasm", instance: "wasm-instance", data: {}, urls: {} } }),
  );
});

afterEach(() => {
  document.body.replaceChildren();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const stubFetch = (responses: (() => Response | Promise<Response>)[]): void => {
  const queue = [...responses];
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (
        input: string | URL,
        init?: { readonly body?: string; readonly signal?: AbortSignal },
      ) => {
        const url = input.toString();
        calls.push({ url, body: init?.body === undefined ? undefined : JSON.parse(init.body) });
        const next = queue.shift();
        if (!next) {
          throw new Error(`Unexpected request to ${url}`);
        }
        const response = await next();
        init?.signal?.throwIfAborted();
        return response;
      },
    ),
  );
};

const pending = () => {
  let resolve: (response: Response) => void = () => {};
  const response = new Promise<Response>((settle) => (resolve = settle));
  return { response: () => response, resolve };
};

test("renders posted values and renders again for a change that arrives mid-render", async () => {
  const first = pending();
  stubFetch([first.response, () => svg()]);
  const { viewer, host } = mount();

  settle(host, 1);
  await vi.waitFor(() => expect(calls).toHaveLength(1));
  settle(host, 2);
  await vi.advanceTimersByTimeAsync(1000);
  expect(calls).toHaveLength(1);
  first.resolve(svg());

  await vi.waitFor(() => expect(calls).toHaveLength(2));
  expect(calls.map(({ body }) => body)).toEqual([
    { revision: "presentation-revision", values: { total: 1 }, outputs: {}, cells: {} },
    { revision: "presentation-revision", values: { total: 2 }, outputs: {}, cells: {} },
  ]);
  expect(calls[0]?.url).toMatch(/\/_marimo-studio\/views\/dashboard\/render$/);
  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));
});

test("renders once a stale value settles without changing", async () => {
  stubFetch([() => svg()]);
  const { viewer, host } = mount();
  Object.defineProperty(host, "marimoValue", { configurable: true, get: () => 1 });
  host.dataset.state = "stale";

  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));
  expect(calls.map(({ body }) => body)).toEqual([
    { revision: "presentation-revision", values: { total: 1 }, outputs: {}, cells: {} },
  ]);
});

test("retries a render that the server reports as temporarily unavailable", async () => {
  const unavailable = () => failure(409, { error: "render-unavailable", transient: true });
  stubFetch([unavailable, () => svg()]);
  const { viewer, host } = mount();

  settle(host, 1);

  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));
  expect(calls).toHaveLength(2);
});

test("reports a render that stays unavailable after its retries", async () => {
  const unavailable = () =>
    failure(409, { error: "render-unavailable", message: "Busy.", transient: true });
  stubFetch([unavailable, unavailable, unavailable, unavailable, () => svg()]);
  const { viewer, host } = mount();

  settle(host, 1);

  await vi.waitFor(() => expect(viewer.dataset.state).toBe("error"), { timeout: 5000 });
  expect(calls.map(({ url }) => url.split("/").pop())).toEqual([
    "render",
    "render",
    "render",
    "render",
    "card.svg",
  ]);
  expect(shadow(viewer).querySelector("[role=alert]")?.textContent).toBe("Busy.");
});

test("shows the published document with a note in a browser runtime's run mode", async () => {
  commitRuntimeConfig(
    runtimeConfig({
      runtime: { id: "wasm", instance: "wasm-instance", data: {}, urls: {} },
      mode: "run",
    }),
  );
  stubFetch([() => svg()]);
  const { viewer, host } = mount();

  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));
  settle(host, 1);
  settle(host, 2);
  await vi.advanceTimersByTimeAsync(1000);

  expect(calls.map(({ url }) => url.split("/").pop())).toEqual(["card.svg"]);
  expect(shadow(viewer).querySelector("[role=status]")?.textContent).toBe(
    "Showing the document without current notebook values.",
  );
});

test("reports render diagnostics beside the last document", async () => {
  stubFetch([
    () => svg(),
    () =>
      failure(422, {
        error: "render-failed",
        diagnostics: [
          {
            code: "typst-compile-error",
            severity: "error",
            message: "unknown variable: totl",
            hint: "",
            source: { path: "main.typ", line: 4, column: 2 },
          },
        ],
      }),
  ]);
  const { viewer, host } = mount();
  settle(host, 1);
  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));

  settle(host, 2);

  await vi.waitFor(() => expect(viewer.dataset.state).toBe("error"));
  const alert = shadow(viewer).querySelector("[role=alert]")?.textContent;
  expect(alert).toContain("unknown variable: totl");
  expect(alert).toContain("main.typ:4");
  expect(shadow(viewer).querySelector("img")?.alt).toBe("card.svg");
});

test("drops a render that finishes after the viewer leaves the page", async () => {
  const late = pending();
  stubFetch([late.response]);
  const { viewer, host } = mount();
  settle(host, 1);
  await vi.waitFor(() => expect(calls).toHaveLength(1));

  viewer.remove();
  await vi.advanceTimersByTimeAsync(0);
  late.resolve(svg());
  await vi.advanceTimersByTimeAsync(1000);

  expect(calls).toHaveLength(1);
  expect(objectUrls).toBe(0);
  expect(shadow(viewer).querySelector("img")).toBeNull();
});

const mountOutput = () => {
  document.body.innerHTML = `
    <main id="app-shell">
      <marimo-document src="card.svg" type="image/svg+xml" render>
        <span hidden mo-value="total" data-marimo-studio-site="site-total"></span>
        <marimo-output hidden value="chart" data-marimo-studio-site="site-chart"></marimo-output>
      </marimo-document>
    </main>
  `;
  const viewer = document.querySelector<HTMLElement>("marimo-document");
  const host = document.querySelector<HTMLElement>("[mo-value]");
  const output = document.querySelector<HTMLElement>("marimo-output");
  if (!viewer || !host || !output) {
    throw new Error("The output fixture did not mount");
  }
  return { viewer, host, output };
};

// Output runtimes expose the rendered output and mark the host ready.
const settleOutput = (host: HTMLElement, data: string): void => {
  Object.assign(host, { marimoOutput: { mimetype: "image/svg+xml", data } });
  host.dataset.state = "ready";
  host.dispatchEvent(new CustomEvent("marimo-output-updated", { bubbles: true, composed: true }));
};

test("posts the outputs its hosts show and renders again when one changes", async () => {
  stubFetch([() => svg(), () => svg()]);
  const { viewer, host, output } = mountOutput();

  settle(host, 1);
  settleOutput(output, "data:image/svg+xml;base64,b25l");
  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));
  settleOutput(output, "data:image/svg+xml;base64,dHdv");

  await vi.waitFor(() => expect(calls).toHaveLength(2));
  expect(calls.map(({ body }) => body)).toEqual([
    {
      revision: "presentation-revision",
      values: { total: 1 },
      outputs: { chart: { mimetype: "image/svg+xml", data: "data:image/svg+xml;base64,b25l" } },
      cells: {},
    },
    {
      revision: "presentation-revision",
      values: { total: 1 },
      outputs: { chart: { mimetype: "image/svg+xml", data: "data:image/svg+xml;base64,dHdv" } },
      cells: {},
    },
  ]);
});

test("names an unavailable output that the document shows with its default", async () => {
  stubFetch([() => svg()]);
  const { viewer, host, output } = mountOutput();

  settle(host, 1);
  output.dataset.state = "error";
  output.dataset.marimoDiagnosticMessage = "Selector 'chart' exceeds the 5000000-byte limit.";
  output.dispatchEvent(new CustomEvent("marimo-output-error", { bubbles: true, composed: true }));

  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));
  expect(calls.map(({ body }) => body)).toEqual([
    { revision: "presentation-revision", values: { total: 1 }, outputs: {}, cells: {} },
  ]);
  expect(shadow(viewer).querySelector("[role=status]")?.textContent).toBe(
    "Showing the default for chart (Selector 'chart' exceeds the 5000000-byte limit).",
  );
});

const preparedState = (fingerprint: string) => ({
  inputs: () => ({ mode: "baseline" }),
  states: () => [{ inputs: { mode: "baseline" }, fingerprint }],
});

test("renders a Prepared edit preview from the values its hosts show", async () => {
  vi.stubGlobal("marimoStudio", { state: preparedState("a".repeat(64)) });
  commitRuntimeConfig(
    runtimeConfig({ runtime: { id: "zero-python", instance: "prepared", data: {}, urls: {} } }),
  );
  stubFetch([() => svg()]);
  const { viewer, host } = mount();

  settle(host, 1);

  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));
  expect(calls).toEqual([
    {
      url: expect.stringMatching(/\/_marimo-studio\/views\/dashboard\/render$/),
      body: { revision: "presentation-revision", values: { total: 1 }, outputs: {}, cells: {} },
    },
  ]);
});

test("shows a Prepared view's rendition for the state the reader selects", async () => {
  vi.stubGlobal("marimoStudio", { state: preparedState("b".repeat(64)) });
  commitRuntimeConfig(
    runtimeConfig({
      runtime: { id: "zero-python", instance: "prepared", data: {}, urls: {} },
      mode: "run",
    }),
  );
  stubFetch([() => svg()]);
  const { viewer, host } = mount();

  settle(host, 1);

  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));
  expect(calls.map(({ url, body }) => [new URL(url).pathname, body])).toEqual([
    [`/renditions/${"b".repeat(64)}.svg`, undefined],
  ]);
});

test("posts the output each cell host shows", async () => {
  stubFetch([() => svg()]);
  document.body.innerHTML = `
    <main id="app-shell">
      <marimo-document src="card.svg" type="image/svg+xml" render>
        <marimo-cell hidden name="plot" data-marimo-studio-site="site-plot"></marimo-cell>
      </marimo-document>
    </main>
  `;
  const viewer = document.querySelector<HTMLElement>("marimo-document");
  const cell = document.querySelector<HTMLElement>("marimo-cell");
  if (!viewer || !cell) {
    throw new Error("The cell fixture did not mount");
  }
  const output = {
    mimetype: "application/vnd.marimo+mimebundle",
    data: { "image/png": "data:image/png;base64,cG5n" },
  };

  // Cell runtimes expose the cell's output and mark the host ready.
  Object.assign(cell, { marimoOutput: output });
  cell.dataset.state = "ready";
  cell.dispatchEvent(new CustomEvent("marimo-cell-ready", { bubbles: true, composed: true }));

  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));
  expect(calls.map(({ body }) => body)).toEqual([
    { revision: "presentation-revision", values: {}, outputs: {}, cells: { plot: output } },
  ]);
});

test("keeps the painted document when a render returns the same bytes", async () => {
  stubFetch([() => svg(), () => svg()]);
  const { viewer, host } = mount();

  settle(host, 1);
  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));
  const painted = shadow(viewer).querySelector("img");
  settle(host, 2);
  await vi.waitFor(() => expect(calls).toHaveLength(2));
  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));

  expect(painted).not.toBeNull();
  expect(shadow(viewer).querySelector("img")).toBe(painted);
});

test("retries a render after a dropped connection", async () => {
  stubFetch([
    () => {
      throw new TypeError("Failed to fetch");
    },
    () => svg(),
  ]);
  const { viewer, host } = mount();

  settle(host, 1);

  await vi.waitFor(() => expect(calls).toHaveLength(2));
  await vi.waitFor(() => expect(viewer.dataset.state).toBe("ready"));
  expect(shadow(viewer).querySelector(".problems")?.childElementCount).toBe(0);
});
