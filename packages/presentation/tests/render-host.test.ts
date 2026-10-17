import type { ArtifactSite } from "@marimo-studio/protocol/projections";
import type { JsonValue } from "@marimo-studio/protocol/runtime-config";

import { afterEach, beforeAll, beforeEach, expect, test, vi } from "vite-plus/test";
import { z } from "zod";

import type { RenderReads } from "../src/renders/inputs.ts";

import { registerMarimoOutputElement, type MarimoOutputElement } from "../src/outputs/host.ts";
import { readiness } from "../src/readiness.ts";
import {
  notifyNotebookResults,
  publishPreparedState,
  publishRenderInputReader,
} from "../src/renders/inputs.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { setRuntimeConnectionState } from "../src/runtime-state.ts";
import { projectionRuntimeConfig, runtimeConfig } from "./runtime-fixtures.ts";

const SUPPORT = "http://localhost:3000/proxy/app/_marimo-studio/views/dashboard";
const RENDERS = `${SUPPORT}/renders`;

interface Call {
  readonly url: string;
  readonly method: string;
  readonly session: string | null;
  readonly body: unknown;
}

type Reply = (signal?: AbortSignal) => Response | Promise<Response>;

const json = (body: JsonValue, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const file = (path: string, mediaType: string) => ({
  path,
  mediaType,
  sha256: "f".repeat(64),
  size: 4,
});

interface BundleOptions {
  readonly files?: readonly ReturnType<typeof file>[];
  readonly main?: string;
  readonly preview?: string | null;
  readonly absent?: readonly string[];
  readonly regions?: readonly JsonValue[];
}

const bundle = (id: string, options: BundleOptions = {}) => ({
  render: "figure.py",
  bundle: id.repeat(64),
  files: options.files ?? [file("figure.png", "image/png")],
  main: options.main ?? "figure.png",
  preview: options.preview ?? null,
  warnings: [],
  absent: options.absent ?? [],
  regions: options.regions ?? [],
});

const pending = () => {
  let resolve: (response: Response) => void = () => {};
  const aborted = { value: false };
  const response = new Promise<Response>((settle) => (resolve = settle));
  const reply: Reply = (signal) =>
    new Promise<Response>((settle, reject) => {
      signal?.addEventListener("abort", () => {
        aborted.value = true;
        reject(signal.reason);
      });
      void response.then(settle);
    });
  return { reply, resolve, aborted };
};

let calls: Call[] = [];
let renders: Reply[] = [];
let index: Reply = () => new Response(null, { status: 404 });

const stubFetch = () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = input.toString();
      calls.push({
        url,
        method: init?.method ?? "GET",
        session: new Headers(init?.headers).get("Marimo-Session-Id"),
        body: init?.body === undefined ? undefined : JSON.parse(z.string().parse(init.body)),
      });
      if (url === `${RENDERS}/index.json`) {
        return index();
      }
      const next = renders.shift();
      if (!next) {
        throw new Error(`Unexpected request to ${url}`);
      }
      return next(init?.signal ?? undefined);
    }),
  );
};

const posts = () => calls.filter(({ method }) => method === "POST");

const mount = (markup = `<marimo-output render="figure.py"></marimo-output>`) => {
  document.body.innerHTML = `<main id="app-shell">${markup}</main>`;
  const host = document.querySelector<MarimoOutputElement>("marimo-output");
  if (!host?.shadowRoot) {
    throw new Error("The render host did not mount");
  }
  const events: CustomEvent[] = [];
  for (const name of ["marimo-output-ready", "marimo-output-updated", "marimo-output-error"]) {
    document.addEventListener(name, (event) => {
      if (event instanceof CustomEvent) {
        events.push(event);
      }
    });
  }
  return { host, shadow: host.shadowRoot, events };
};

const shown = (shadow: ShadowRoot) => shadow.querySelector<HTMLElement>('[part="content"] > *');

const READ_ACCEPT = {
  value: ["application/json"],
  output: ["image/png"],
  cell: ["image/png"],
} as const;

const site = (
  id: string,
  kind: ArtifactSite["kind"],
  target: string,
  render: string | null,
): ArtifactSite => ({
  id,
  kind,
  source: { path: "src/index.html", line: 1, column: 1 },
  targets: [target],
  accept: render === null ? [] : [...READ_ACCEPT[kind]],
  size: null,
  render,
});

const browserRuntime = (mode: "edit" | "run", id = "wasm") =>
  runtimeConfig({ runtime: { id, instance: `${id}-instance`, data: {}, urls: {} }, mode });

beforeAll(() => {
  registerMarimoOutputElement();
  HTMLImageElement.prototype.decode = () => Promise.resolve();
  HTMLMediaElement.prototype.load = () => {};
});

beforeEach(() => {
  vi.useFakeTimers();
  calls = [];
  renders = [];
  index = () => new Response(null, { status: 404 });
  stubFetch();
  readiness.start();
  setRuntimeConnectionState("ready");
});

afterEach(() => {
  document.body.replaceChildren();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

test("the Python runtime names the render and the host shows its bundle", async () => {
  commitRuntimeConfig(runtimeConfig());
  renders.push(() => json(bundle("a")));
  const { host, shadow, events } = mount();

  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));

  expect(posts()).toEqual([
    {
      url: `${SUPPORT}/render`,
      method: "POST",
      session: "s_view01",
      body: { revision: "presentation-revision", render: "figure.py" },
    },
  ]);
  const url = `${RENDERS}/${"a".repeat(64)}/figure.png`;
  expect(shown(shadow)?.getAttribute("src")).toBe(url);
  expect(shadow.querySelector("a")?.getAttribute("href")).toBe(url);
  expect(shadow.querySelector("a")?.getAttribute("download")).toBe("figure.png");
  expect(host.hasAttribute("aria-busy")).toBe(false);
  expect(events.map(({ type }) => type)).toEqual(["marimo-output-ready"]);
  expect(events[0]?.detail).toMatchObject({
    render: "figure.py",
    bundle: "a".repeat(64),
    main: "figure.png",
    files: [{ path: "figure.png", mediaType: "image/png", size: 4, url }],
  });
  expect(host.marimoRender).toEqual(events[0]?.detail);
});

test("a newer render keeps the last bundle stale, and a failure keeps it beside diagnostics", async () => {
  commitRuntimeConfig(runtimeConfig());
  const second = pending();
  renders.push(() => json(bundle("a")), second.reply);
  const { host, shadow, events } = mount();
  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));
  const first = host.marimoRender;

  notifyNotebookResults();
  await vi.waitFor(() => expect(host.dataset.state).toBe("stale"));
  expect(host.hasAttribute("aria-busy")).toBe(true);
  expect(shown(shadow)?.getAttribute("src")).toContain("a".repeat(64));

  second.resolve(
    json(
      {
        error: "render-failed",
        diagnostics: [
          {
            code: "figure-failed",
            severity: "error",
            message: "The figure could not be drawn.",
            hint: "Check the plotting cell.",
            source: null,
          },
        ],
      },
      422,
    ),
  );

  await vi.waitFor(() => expect(host.dataset.state).toBe("error"));
  expect(shown(shadow)?.getAttribute("src")).toContain("a".repeat(64));
  expect(shadow.querySelector('[part="problems"]')?.textContent).toContain(
    "The figure could not be drawn.",
  );
  expect(host.marimoRender).toBe(first);
  expect(events.at(-1)?.type).toBe("marimo-output-error");
  expect(events.at(-1)?.detail).toMatchObject({
    render: "figure.py",
    code: "figure-failed",
    message: "The figure could not be drawn.",
    hint: "Check the plotting cell.",
    diagnostics: [{ code: "figure-failed" }],
  });
});

test("repeated failures report one error until a render succeeds again", async () => {
  commitRuntimeConfig(runtimeConfig());
  const failure = () =>
    json({ error: "render-failed", message: "The figure could not be drawn." }, 422);
  renders.push(failure, failure, () => json(bundle("a")), failure);
  const { host, events } = mount();
  const settled = async (count: number) => {
    await vi.waitFor(() => expect(posts()).toHaveLength(count));
    await vi.waitFor(() => expect(host.getAttribute("aria-busy")).toBeNull());
  };

  await settled(1);
  notifyNotebookResults();
  await settled(2);
  expect(host.dataset.state).toBe("error");
  expect(events.map(({ type }) => type)).toEqual(["marimo-output-error"]);

  notifyNotebookResults();
  await settled(3);
  notifyNotebookResults();
  await settled(4);

  expect(host.dataset.state).toBe("error");
  expect(events.map(({ type }) => type)).toEqual([
    "marimo-output-error",
    "marimo-output-ready",
    "marimo-output-error",
  ]);
});

test("notebook results during a render cancel it, and one request renders the burst", async () => {
  commitRuntimeConfig(runtimeConfig());
  renders.push(() => json(bundle("a")));
  const { host, shadow, events } = mount();
  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));
  const outdated = pending();
  renders.push(outdated.reply, () => json(bundle("b")));

  notifyNotebookResults();
  await vi.waitFor(() => expect(posts()).toHaveLength(2));
  notifyNotebookResults();
  notifyNotebookResults();

  expect(outdated.aborted.value).toBe(true);
  expect(host.dataset.state).toBe("stale");
  expect(shown(shadow)?.getAttribute("src")).toContain("a".repeat(64));
  await vi.waitFor(() => expect(shown(shadow)?.getAttribute("src")).toContain("b".repeat(64)));
  expect(posts()).toHaveLength(3);
  expect(host.dataset.state).toBe("ready");
  expect(events.map(({ type }) => type)).toEqual(["marimo-output-ready", "marimo-output-updated"]);
});

test("results that change faster than renders finish still show each finished render", async () => {
  commitRuntimeConfig(runtimeConfig());
  renders.push(() => json(bundle("a")));
  const { host, shadow } = mount();
  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));
  const outdated = pending();
  const replacement = pending();
  renders.push(outdated.reply, replacement.reply, () => json(bundle("d")));

  notifyNotebookResults();
  await vi.waitFor(() => expect(posts()).toHaveLength(2));
  notifyNotebookResults();
  await vi.waitFor(() => expect(posts()).toHaveLength(3));
  notifyNotebookResults();
  await vi.advanceTimersByTimeAsync(1_000);

  expect(outdated.aborted.value).toBe(true);
  expect(replacement.aborted.value).toBe(false);
  expect(posts()).toHaveLength(3);
  replacement.resolve(json(bundle("c")));
  await vi.waitFor(() => expect(shown(shadow)?.getAttribute("src")).toContain("c".repeat(64)));
  await vi.waitFor(() => expect(shown(shadow)?.getAttribute("src")).toContain("d".repeat(64)));
  expect(posts()).toHaveLength(4);
});

test("a transient conflict retries until the notebook settles", async () => {
  commitRuntimeConfig(runtimeConfig());
  renders.push(
    () =>
      json(
        {
          error: "render-inputs-unsettled",
          message: "The notebook is running.",
          transient: true,
        },
        409,
      ),
    () => json(bundle("a")),
  );
  const { host } = mount();

  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));
  expect(posts()).toHaveLength(2);
});

test("a browser runtime in edit mode posts the render's reads without the page's hosts", async () => {
  commitRuntimeConfig({
    ...browserRuntime("edit"),
    sites: [
      site("page-total", "value", "total", null),
      site("read-total", "value", "total", "figure.py"),
      site("read-chart", "output", "chart", "figure.py"),
      site("read-summary", "cell", "summary", "figure.py"),
      site("read-other", "value", "other", "table.py"),
    ],
  });
  const reads: RenderReads[] = [];
  const release = publishRenderInputReader(async (render, requested) => {
    expect(render).toBe("figure.py");
    reads.push(requested);
    return {
      values: { total: 3 },
      outputs: { chart: { mimetype: "image/png", data: "data:image/png;base64,AA==" } },
      cells: {},
    };
  });
  renders.push(() => json(bundle("a", { absent: ["summary"] })));
  const { host, shadow } = mount();

  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));
  release();

  expect(reads).toEqual([
    {
      revision: "presentation-revision",
      values: [
        { siteId: "read-total", instanceId: "render:figure.py:read-total", target: "total" },
      ],
      outputs: [
        { siteId: "read-chart", instanceId: "render:figure.py:read-chart", target: "chart" },
      ],
      cells: [
        { siteId: "read-summary", instanceId: "render:figure.py:read-summary", target: "summary" },
      ],
    },
  ]);
  expect(posts().map(({ body }) => body)).toEqual([
    {
      revision: "presentation-revision",
      render: "figure.py",
      values: { total: 3 },
      outputs: { chart: { mimetype: "image/png", data: "data:image/png;base64,AA==" } },
      cells: {},
    },
  ]);
  expect(shadow.querySelector("[role=status]")?.textContent).toContain("summary");
});

test("a browser runtime outside edit mode reports that no notebook results reach the render", async () => {
  commitRuntimeConfig(browserRuntime("run"));
  const { host, events } = mount();

  await vi.waitFor(() => expect(host.dataset.state).toBe("error"));

  expect(posts()).toEqual([]);
  expect(events.map(({ type, detail }) => [type, detail.code])).toEqual([
    ["marimo-output-error", "render-results-unavailable"],
  ]);
  expect(host.dataset.marimoDiagnosticCode).toBe("render-results-unavailable");
});

test("a static export shows the bundle rendered for the prepared state in view", async () => {
  commitRuntimeConfig(browserRuntime("run", "zero-python"));
  let current = "state-b";
  const release = publishPreparedState(() => current);
  const indexed = ({
    render,
    bundle: id,
    warnings,
    absent,
    ...content
  }: ReturnType<typeof bundle>) => ({
    bundles: { [id]: content },
    entry: { [render]: { bundle: id, warnings, absent } },
  });
  const [a, b] = [indexed(bundle("a")), indexed(bundle("b"))];
  index = () =>
    json({
      schema: 2,
      bundles: { ...a.bundles, ...b.bundles },
      states: { "state-a": a.entry, "state-b": b.entry },
    });
  const { host, shadow, events } = mount();

  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));
  expect(shown(shadow)?.getAttribute("src")).toBe(`${RENDERS}/${"b".repeat(64)}/figure.png`);

  current = "state-a";
  notifyNotebookResults();

  await vi.waitFor(() => expect(shown(shadow)?.getAttribute("src")).toContain("a".repeat(64)));
  release();
  expect(posts()).toEqual([]);
  expect(events.map(({ type }) => type)).toEqual(["marimo-output-ready", "marimo-output-updated"]);
});

test("a video plays from its file URL with the preview as poster", async () => {
  commitRuntimeConfig(runtimeConfig());
  renders.push(() =>
    json(
      bundle("a", {
        files: [file("scene.mp4", "video/mp4"), file("poster.png", "image/png")],
        main: "scene.mp4",
        preview: "poster.png",
      }),
    ),
  );
  const { host, shadow } = mount();

  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));

  const video = shadow.querySelector("video");
  expect(video?.getAttribute("src")).toBe(`${RENDERS}/${"a".repeat(64)}/scene.mp4`);
  expect(video?.getAttribute("poster")).toBe(`${RENDERS}/${"a".repeat(64)}/poster.png`);
  expect(video?.controls).toBe(true);
});

test("markup inside the host replaces the stock presentation and reads the record", async () => {
  commitRuntimeConfig(runtimeConfig());
  renders.push(() =>
    json(
      bundle("a", {
        files: [file("scene.mp4", "video/mp4"), file("poster.png", "image/png")],
        main: "scene.mp4",
        preview: "poster.png",
      }),
    ),
  );
  const { host, shadow } = mount(
    `<marimo-output render="figure.py"><video id="player"></video></marimo-output>`,
  );

  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));

  expect(shadow.querySelector("video")).toBeNull();
  expect(host.marimoRender?.files.map(({ path, url }) => [path, url])).toEqual([
    ["scene.mp4", `${RENDERS}/${"a".repeat(64)}/scene.mp4`],
    ["poster.png", `${RENDERS}/${"a".repeat(64)}/poster.png`],
  ]);
  expect(shadow.querySelector("a")?.getAttribute("href")).toBe(
    `${RENDERS}/${"a".repeat(64)}/scene.mp4`,
  );
});

test("a main file without a presenter shows its preview and offers the main file", async () => {
  commitRuntimeConfig(runtimeConfig());
  const docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  renders.push(() =>
    json(
      bundle("a", {
        files: [file("out/report.docx", docx), file("out/page-1.png", "image/png")],
        main: "out/report.docx",
        preview: "out/page-1.png",
      }),
    ),
  );
  const { host, shadow } = mount();

  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));

  expect(shown(shadow)?.getAttribute("src")).toBe(`${RENDERS}/${"a".repeat(64)}/out/page-1.png`);
  const download = shadow.querySelector("a");
  expect(download?.getAttribute("href")).toBe(`${RENDERS}/${"a".repeat(64)}/out/report.docx`);
  expect(download?.getAttribute("download")).toBe("report.docx");
});

test("generated HTML shows in a frame without the page's origin", async () => {
  commitRuntimeConfig(runtimeConfig());
  renders.push(() =>
    json(bundle("a", { files: [file("index.html", "text/html")], main: "index.html" })),
  );
  const { host, shadow } = mount();

  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));

  const frame = shadow.querySelector("iframe");
  expect(frame?.getAttribute("src")).toBe(`${RENDERS}/${"a".repeat(64)}/index.html`);
  expect(frame?.getAttribute("sandbox")).toBe("allow-scripts");
});

test("a host with both render and value attributes reports an invalid host", async () => {
  commitRuntimeConfig(runtimeConfig());
  const { host } = mount(`<marimo-output render="figure.py" value="chart"></marimo-output>`);

  await vi.waitFor(() => expect(host.dataset.state).toBe("error"));

  expect(host.dataset.marimoDiagnosticCode).toBe("render-host-invalid");
  expect(posts()).toEqual([]);
});

test("a host whose render leaves the project reports an invalid host", async () => {
  commitRuntimeConfig(runtimeConfig());
  const { host } = mount(`<marimo-output render="../main.typ"></marimo-output>`);

  await vi.waitFor(() => expect(host.dataset.state).toBe("error"));

  expect(host.dataset.marimoDiagnosticCode).toBe("render-host-invalid");
  expect(posts()).toEqual([]);
});

test("removing the page's markup shows the current render with the stock presentation", async () => {
  commitRuntimeConfig(runtimeConfig());
  renders.push(() =>
    json(bundle("a", { files: [file("scene.mp4", "video/mp4")], main: "scene.mp4" })),
  );
  const { host, shadow } = mount(
    `<marimo-output render="figure.py"><video id="player"></video></marimo-output>`,
  );
  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));

  host.querySelector("#player")?.remove();

  await vi.waitFor(() =>
    expect(shadow.querySelector("video")?.getAttribute("src")).toBe(
      `${RENDERS}/${"a".repeat(64)}/scene.mp4`,
    ),
  );
});

// The render reads one value, one output, and one cell, each produced by its own cell.
const commitRenderReads = (cellRefs?: Record<string, string>) => {
  const config = projectionRuntimeConfig([
    { siteId: "read-joint", instanceId: "joint", target: "joint", kind: "value" },
    { siteId: "read-chart", instanceId: "chart", target: "chart", kind: "output" },
    { siteId: "read-summary", instanceId: "summary", target: "summary", kind: "cell" },
  ]);
  commitRuntimeConfig({
    ...config,
    sites: config.sites.map((item) => ({
      ...item,
      render: "figure.py",
      accept: [...READ_ACCEPT[item.kind]],
    })),
    runtimeBindings: cellRefs ? { cellRefs } : config.runtimeBindings,
  });
};

const region = (changes: Record<string, JsonValue>) => ({
  file: "figure.png",
  rect: { x: 0, y: 0, width: 1, height: 1 },
  reads: [],
  source: null,
  label: null,
  page: null,
  start: null,
  end: null,
  ...changes,
});

const sources = (element: Element) =>
  Array.from(
    element.querySelectorAll<HTMLElement>(":scope > [data-marimo-lens-cell-id]"),
    (item) => ({
      cellId: item.dataset.marimoLensCellId,
      selector: item.dataset.marimoLensSelector ?? null,
      hidden: item.hidden,
    }),
  );

const regionTargets = (host: Element) =>
  Array.from(host.querySelectorAll<HTMLElement>("[data-marimo-studio-region]"));

test("regions of a rendered file are Lens targets that name the cells producing them", async () => {
  commitRenderReads();
  renders.push(() =>
    json(
      bundle("a", {
        regions: [
          region({
            rect: { x: 0.5, y: 0.25, width: 0.25, height: 0.5 },
            reads: ["joint[2][3]"],
            source: { path: "figure.py", line: 12, column: 5 },
            label: "Square",
          }),
          region({ reads: ["chart", "summary"] }),
        ],
      }),
    ),
  );
  const { host, shadow } = mount();

  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));

  expect(shown(shadow)?.getAttribute("src")).toContain("a".repeat(64));
  // Smaller regions come later, so they sit above the regions around them.
  const [whole, square] = regionTargets(host);
  expect(whole?.dataset.marimoLensLabel).toBe("chart");
  expect(sources(whole!)).toEqual([
    { cellId: "chart-cell", selector: "chart", hidden: true },
    { cellId: "summary-cell", selector: null, hidden: true },
  ]);
  expect(square?.hasAttribute("data-marimo-lens-target")).toBe(true);
  expect(square?.dataset.marimoLensLabel).toBe("Square");
  expect(square?.dataset.marimoLensDetail).toBe("figure.png");
  expect(JSON.parse(square?.dataset.marimoLensRenderSource ?? "null")).toEqual({
    path: "figure.py",
    line: 12,
    column: 5,
  });
  expect(sources(square!)).toEqual([
    { cellId: "joint-cell", selector: "joint[2][3]", hidden: true },
  ]);
  expect(JSON.parse(square?.dataset.marimoLensMedia ?? "null")).toEqual({ path: "figure.png" });
  expect(square?.style).toMatchObject({ left: "50%", top: "25%", width: "25%", height: "50%" });
  // The host traces the whole file to every read of the render.
  expect(sources(host)).toEqual([
    { cellId: "joint-cell", selector: "joint", hidden: true },
    { cellId: "chart-cell", selector: "chart", hidden: true },
    { cellId: "summary-cell", selector: null, hidden: true },
  ]);
  expect(host.dataset.marimoLensContext).toBe("");
  expect(host.dataset.marimoLensLabel).toBe("figure.py");
  // The host names exactly its own sources, apart from those of its regions.
  const inputs = host.dataset.marimoLensInputs?.split(" ") ?? [];
  expect(inputs.map((id) => document.getElementById(id)?.parentElement)).toEqual([
    host,
    host,
    host,
  ]);
});

test("regions follow the images a page presents itself", async () => {
  commitRenderReads();
  renders.push(() => json(bundle("a", { regions: [region({ reads: ["chart"] })] })));
  const { host } = mount(
    `<marimo-output render="figure.py"><img alt="Figure"><p>Caption</p></marimo-output>`,
  );
  host.addEventListener("marimo-output-ready", () => {
    host.querySelector("img")!.src = host.marimoRender!.files[0]!.url;
  });

  await vi.waitFor(() => expect(regionTargets(host)).toHaveLength(1));

  const layer = host.querySelector<HTMLElement>("[data-marimo-studio-regions]");
  expect(layer?.slot).toBe("marimo-regions");
  expect(sources(regionTargets(host)[0]!)).toEqual([
    { cellId: "chart-cell", selector: "chart", hidden: true },
  ]);

  host.querySelector("img")!.removeAttribute("src");
  await vi.waitFor(() => expect(regionTargets(host)).toHaveLength(0));
});

test("a newer bundle replaces the regions, and a removed host releases them", async () => {
  commitRenderReads();
  renders.push(
    () => json(bundle("a", { regions: [region({ reads: ["chart"], label: "First" })] })),
    () => json(bundle("b", { regions: [region({ reads: ["joint"], label: "Second" })] })),
  );
  const { host } = mount();
  await vi.waitFor(() => expect(regionTargets(host)[0]?.dataset.marimoLensLabel).toBe("First"));

  notifyNotebookResults();

  await vi.waitFor(() => expect(regionTargets(host)[0]?.dataset.marimoLensLabel).toBe("Second"));
  expect(regionTargets(host)).toHaveLength(1);
  host.remove();
  await Promise.resolve();
  expect(regionTargets(host)).toHaveLength(0);
  expect(sources(host)).toEqual([]);
  expect(host.hasAttribute("data-marimo-lens-context")).toBe(false);
  expect(host.hasAttribute("data-marimo-lens-inputs")).toBe(false);
});

test("regions keep their targets until their producers change", async () => {
  commitRenderReads();
  renders.push(() => json(bundle("a", { regions: [region({ reads: ["chart"] })] })));
  const { host } = mount();
  await vi.waitFor(() => expect(regionTargets(host)).toHaveLength(1));
  const [first] = regionTargets(host);

  commitRenderReads();
  expect(regionTargets(host)).toEqual([first]);

  commitRenderReads({
    "cell:v1:joint": "joint-cell",
    "cell:v1:chart": "chart-restarted",
    "cell:v1:summary": "summary-cell",
  });
  const [second] = regionTargets(host);
  expect(second).not.toBe(first);
  expect(sources(second!)).toEqual([
    { cellId: "chart-restarted", selector: "chart", hidden: true },
  ]);
});

test("regions move between the page's markup and the stock presentation", async () => {
  commitRenderReads();
  renders.push(() => json(bundle("a", { regions: [region({ reads: ["chart"] })] })));
  const { host } = mount(`<marimo-output render="figure.py"><img alt="Figure"></marimo-output>`);
  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));
  expect(regionTargets(host)).toHaveLength(0);

  host.querySelector("img")!.remove();
  await vi.waitFor(() => expect(regionTargets(host)).toHaveLength(1));

  host.append(document.createElement("canvas"));
  await vi.waitFor(() => expect(regionTargets(host)).toHaveLength(0));
});

test("a video shows the regions of its poster, then of the frames it plays", async () => {
  commitRenderReads();
  renders.push(() =>
    json(
      bundle("a", {
        files: [file("scene.mp4", "video/mp4"), file("poster.png", "image/png")],
        main: "scene.mp4",
        preview: "poster.png",
        regions: [
          region({ file: "poster.png", label: "Title" }),
          region({ file: "scene.mp4", label: "Square", start: 0, end: 1 }),
          region({ file: "scene.mp4", label: "Circle", start: 1, end: 2 }),
        ],
      }),
    ),
  );
  const { host, shadow } = mount();
  await vi.waitFor(() => expect(regionTargets(host)).toHaveLength(3));
  const visible = () =>
    regionTargets(host)
      .filter((element) => element.style.display !== "none")
      .map((element) => element.dataset.marimoLensLabel);
  expect(visible()).toEqual(["Title"]);
  expect(JSON.parse(regionTargets(host)[2]?.dataset.marimoLensMedia ?? "null")).toEqual({
    path: "scene.mp4",
    start: 1,
    end: 2,
  });

  // jsdom does not play media, so the video reports the moment it shows.
  const video = shadow.querySelector("video")!;
  const playing = (time: number) => {
    Object.defineProperties(video, {
      currentTime: { configurable: true, get: () => time },
      played: { configurable: true, get: () => ({ length: 1 }) },
      duration: { configurable: true, get: () => 2 },
    });
    video.dispatchEvent(new Event("timeupdate"));
  };
  playing(0.5);
  expect(visible()).toEqual(["Square"]);
  playing(2);
  expect(visible()).toEqual(["Circle"]);
});

test("an element the page draws a PDF on names its page", async () => {
  commitRenderReads();
  renders.push(() =>
    json(
      bundle("a", {
        files: [file("report.pdf", "application/pdf")],
        main: "report.pdf",
        regions: [region({ file: "report.pdf", page: 1, reads: ["chart"] })],
      }),
    ),
  );
  const { host } = mount(
    `<marimo-output render="figure.py"><canvas data-marimo-render-file="report.pdf"></canvas></marimo-output>`,
  );
  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));
  expect(regionTargets(host)).toHaveLength(0);

  host.querySelector("canvas")!.dataset.marimoRenderPage = "1";

  await vi.waitFor(() => expect(regionTargets(host)).toHaveLength(1));
});
