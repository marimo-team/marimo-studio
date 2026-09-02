import {
  type OutputReadResponse,
  parseOutputReadResponse,
  type RenderedOutput,
} from "@marimo-studio/protocol/output-read";
import { act, createElement, type ComponentProps } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, expect, test, vi } from "vite-plus/test";

import type { MarimoOutputElement } from "../src/outputs/host";
import type { OutputReader } from "../src/outputs/reader";
import type { ResolvedProjection } from "../src/projections/resolution";

import { indexCells } from "../src/cells/index";
import { morphAuthoredShell } from "../src/document/shell-morph";
import { prepareOutputHosts, registerMarimoOutputElement } from "../src/outputs/host";
import { projectionReadGate } from "../src/projections/read-gate.ts";
import {
  setRuntimeConnectionState,
  startRenderedViewObserver,
  stopRenderedViewObserver,
} from "../src/rendered-view-observer";
import { commitRuntimeConfig } from "../src/runtime-config";
import { OutputPortal } from "../src/runtime/outputs/OutputPortal";
import { RuntimeOutputs } from "../src/runtime/outputs/RuntimeOutputs";
import { runtimeCellFixture } from "./runtime-cell-fixture";
import { projectionRequest, projectionRuntimeConfig, runtimeConfig } from "./runtime-fixtures";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "revision-a",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
};

beforeAll(() => registerMarimoOutputElement());
beforeEach(() => commitRuntimeConfig(runtimeConfig({ revision: "revision-a" })));

afterEach(() => {
  vi.clearAllMocks();
  projectionReadGate.release();
  stopRenderedViewObserver();
  document.body.replaceChildren();
});

const runtimeCell = (version: number, id = "source-cell") =>
  runtimeCellFixture({
    id,
    lastRunStartTimestamp: version,
  });

const output = (data: string, timestamp: number): RenderedOutput => ({
  ownerCellId: "projected-owner",
  mimetype: "text/plain",
  data,
  timestamp,
  resetUiObjectIds: [],
});

const resolvedOutput = (
  variable = "report",
  producer = "cell:v1:report",
  runtimeCellId = "source-cell",
  target = "report",
): ResolvedProjection => {
  const request = {
    ...projectionRequest(target, "output"),
    siteId: "site:output:prototype",
  };
  return {
    request,
    site: {
      id: request.siteId,
      kind: "output",
      source: { path: "src/App.tsx", line: 1, column: 1 },
      allowedTargets: [target],
    },
    producer,
    variable,
    selectorPath: [],
    dependencyClosure: [producer],
    runtimeCellId,
    bindingsStale: false,
  };
};

test("retries a preserved output after a presentation refresh aborts its read", async () => {
  document.body.innerHTML = '<marimo-output value="report"></marimo-output><div id="root"></div>';
  const host = document.querySelector<MarimoOutputElement>("marimo-output")!;
  const root = createRoot(document.querySelector("#root")!);
  const revisions: string[] = [];
  let firstReadStarted = () => {};
  const firstRead = new Promise<void>((resolve) => {
    firstReadStarted = resolve;
  });
  const source: OutputReader = (request, signal) => {
    revisions.push(request.revision);
    if (revisions.length === 1) {
      firstReadStarted();
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
    }
    return Promise.resolve({ outputs: { report: output("current", 2) }, errors: {} });
  };
  const readOutputs: OutputReader = (request, signal) =>
    projectionReadGate.run(signal, (activeSignal) => source(request, activeSignal));

  await act(async () => {
    root.render(
      createElement(OutputPortal, {
        activeProjections: [projectionRequest("report", "output")],
        projection: resolvedOutput(),
        resolutionFailure: undefined,
        connectionState: "OPEN",
        developer: true,
        host,
        readOutputs,
        runtimeReady: true,
        cell: runtimeCell(1),
      }),
    );
  });
  await firstRead;

  await act(async () => {
    const refresh = projectionReadGate.begin();
    commitRuntimeConfig(runtimeConfig({ revision: "revision-b" }));
    projectionReadGate.complete(refresh);
    await Promise.resolve();
  });

  expect(revisions).toEqual(["revision-a", "revision-b"]);
  expect(host.dataset.state).toBe("ready");
  expect(host.dataset.outputMime).toBe("text/plain");
  await act(async () => root.unmount());
});

test("keeps readiness stale until the requested source version mounts", async () => {
  document.body.innerHTML = '<marimo-output value="report"></marimo-output><div id="root"></div>';
  const host = document.querySelector<MarimoOutputElement>("marimo-output")!;
  const root = createRoot(document.querySelector("#root")!);
  const events: string[] = [];
  host.addEventListener("marimo-output-ready", () => events.push("ready"));
  host.addEventListener("marimo-output-updated", () => events.push("updated"));
  startRenderedViewObserver(async () => {});
  setRuntimeConnectionState("ready");

  let resolveFirst = (_value: OutputReadResponse) => {};
  let resolveSecond = (_value: OutputReadResponse) => {};
  const first = new Promise<OutputReadResponse>((resolve) => {
    resolveFirst = resolve;
  });
  const second = new Promise<OutputReadResponse>((resolve) => {
    resolveSecond = resolve;
  });
  const readOutputs = vi
    .fn<OutputReader>()
    .mockImplementationOnce(() => first)
    .mockImplementationOnce(() => second);
  const props: Omit<ComponentProps<typeof OutputPortal>, "cell"> = {
    activeProjections: [projectionRequest("report", "output")],
    projection: resolvedOutput(),
    resolutionFailure: undefined,
    connectionState: "OPEN",
    developer: true,
    host,
    readOutputs,
    runtimeReady: true,
  };

  await act(async () => {
    root.render(createElement(OutputPortal, { ...props, cell: runtimeCell(1) }));
  });
  expect(host.dataset.runtimeCellId).toBe("source-cell");
  await act(async () => {
    resolveFirst({ outputs: { report: output("first", 1) }, errors: {} });
    await first;
  });

  expect(host.dataset.state).toBe("ready");
  expect(events).toEqual(["ready"]);
  await globalThis.marimoStudio.ready();

  await act(async () => {
    root.render(createElement(OutputPortal, { ...props, cell: runtimeCell(2) }));
  });
  expect(host.dataset.state).toBe("stale");
  expect(events).toEqual(["ready"]);
  let settled = false;
  const ready = globalThis.marimoStudio.ready().then(() => {
    settled = true;
  });
  await Promise.resolve();
  expect(settled).toBe(false);

  await act(async () => {
    resolveSecond({ outputs: { report: output("second", 2) }, errors: {} });
    await second;
  });
  await ready;

  expect(host.dataset.state).toBe("ready");
  expect(host.dataset.runtimeCellId).toBe("source-cell");
  expect(host.dataset.outputMime).toBe("text/plain");
  expect(events).toEqual(["ready", "updated"]);
  expect(readOutputs).toHaveBeenCalledTimes(2);

  await act(async () => {
    commitRuntimeConfig(runtimeConfig({ revision: "revision-b" }));
    root.render(
      createElement(OutputPortal, {
        ...props,
        activeProjections: [
          projectionRequest("report", "output"),
          projectionRequest("other", "output"),
        ],
        cell: runtimeCell(2),
      }),
    );
  });
  expect(readOutputs).toHaveBeenCalledTimes(2);
  expect(host.dataset.state).toBe("ready");
  expect(host.dataset.runtimeCellId).toBe("source-cell");
  expect(host.dataset.outputMime).toBe("text/plain");

  await act(async () => root.unmount());
});

test("keys output reads by semantic projection identity", async () => {
  document.body.innerHTML = '<marimo-output value="report"></marimo-output><div id="root"></div>';
  const host = document.querySelector<MarimoOutputElement>("marimo-output")!;
  const root = createRoot(document.querySelector("#root")!);
  const readOutputs = vi.fn<OutputReader>((request) => {
    const target = request.projections[0]?.target ?? "report";
    return Promise.resolve({ outputs: { [target]: output("stable", 1) }, errors: {} });
  });
  const renderProjection = async ({
    request,
    producer = "cell:v1:report",
    sourceCellId = "source-cell",
    sourceVersion = 1,
  }: {
    request: ResolvedProjection["request"];
    producer?: string;
    sourceCellId?: string;
    sourceVersion?: number;
  }) => {
    host.setAttribute("value", request.target);
    await act(async () => {
      root.render(
        createElement(OutputPortal, {
          activeProjections: [request],
          projection: {
            ...resolvedOutput(request.target, producer, sourceCellId, request.target),
            request,
          },
          resolutionFailure: undefined,
          connectionState: "OPEN",
          developer: true,
          host,
          readOutputs,
          runtimeReady: true,
          cell: runtimeCell(sourceVersion, sourceCellId),
        }),
      );
    });
  };
  let currentRequest = projectionRequest("report", "output");

  await renderProjection({ request: currentRequest });
  await renderProjection({ request: { ...currentRequest } });

  expect(readOutputs).toHaveBeenCalledOnce();

  currentRequest = { ...currentRequest, target: "report_next" };
  await renderProjection({ request: currentRequest });
  expect(readOutputs).toHaveBeenCalledTimes(2);

  currentRequest = { ...currentRequest, siteId: "site:output:report_next" };
  await renderProjection({ request: currentRequest });
  expect(readOutputs).toHaveBeenCalledTimes(3);

  currentRequest = { ...currentRequest, instanceId: "projection-report_next" };
  await renderProjection({ request: currentRequest });
  expect(readOutputs).toHaveBeenCalledTimes(4);

  await renderProjection({ request: currentRequest, producer: "cell:v1:report_next" });
  expect(readOutputs).toHaveBeenCalledTimes(5);

  await renderProjection({
    request: currentRequest,
    producer: "cell:v1:report_next",
    sourceCellId: "next-cell",
  });
  expect(readOutputs).toHaveBeenCalledTimes(6);

  await renderProjection({
    request: currentRequest,
    producer: "cell:v1:report_next",
    sourceCellId: "next-cell",
    sourceVersion: 2,
  });
  expect(readOutputs).toHaveBeenCalledTimes(7);
  expect(host.dataset.state).toBe("ready");
  await act(async () => root.unmount());
});

test("clears prior projection metadata when its producer changes", async () => {
  document.body.innerHTML = '<marimo-output value="report"></marimo-output><div id="root"></div>';
  const host = document.querySelector<MarimoOutputElement>("marimo-output")!;
  const root = createRoot(document.querySelector("#root")!);
  let resolveFirst = (_value: OutputReadResponse) => {};
  let resolveSecond = (_value: OutputReadResponse) => {};
  const first = new Promise<OutputReadResponse>((resolve) => {
    resolveFirst = resolve;
  });
  const second = new Promise<OutputReadResponse>((resolve) => {
    resolveSecond = resolve;
  });
  const readOutputs = vi
    .fn<OutputReader>()
    .mockImplementationOnce(() => first)
    .mockImplementationOnce(() => second);
  const props: Omit<ComponentProps<typeof OutputPortal>, "projection" | "cell"> = {
    activeProjections: [projectionRequest("report", "output")],
    resolutionFailure: undefined,
    connectionState: "OPEN",
    developer: true,
    host,
    readOutputs,
    runtimeReady: true,
  };

  await act(async () => {
    root.render(
      createElement(OutputPortal, {
        ...props,
        projection: resolvedOutput("first", "cell:v1:first", "source-cell"),
        cell: runtimeCell(1),
      }),
    );
  });
  await act(async () => {
    resolveFirst({ outputs: { report: output("first", 1) }, errors: {} });
    await first;
  });
  expect(host.dataset.state).toBe("ready");
  expect(host.dataset.marimoVariable).toBe("first");
  expect(host.dataset.runtimeCellId).toBe("source-cell");
  expect(host.dataset.outputMime).toBe("text/plain");

  await act(async () => {
    root.render(
      createElement(OutputPortal, {
        ...props,
        projection: resolvedOutput("second", "cell:v1:second", "next-cell"),
        cell: runtimeCell(1, "next-cell"),
      }),
    );
  });
  expect(host.dataset.state).toBe("loading");
  expect(host.dataset.marimoVariable).toBe("second");
  expect(host.dataset.runtimeCellId).toBe("next-cell");
  expect(host.dataset.outputMime).toBeUndefined();

  await act(async () => {
    resolveSecond({ outputs: { report: output("second", 2) }, errors: {} });
    await second;
  });
  expect(host.dataset.state).toBe("ready");
  expect(host.dataset.marimoVariable).toBe("second");
  expect(host.dataset.runtimeCellId).toBe("next-cell");
  expect(host.dataset.outputMime).toBe("text/plain");

  await act(async () => root.unmount());
});

test("retargets a preserved output portal through an authored shell morph", async () => {
  const siteId = "site:output:retarget";
  commitRuntimeConfig({
    ...runtimeConfig(),
    projectionRevision: "f".repeat(64),
    projectionTargets: { cells: {}, variables: {} },
    mounts: [
      {
        id: siteId,
        kind: "output",
        source: { path: "src/index.html", line: 1, column: 1 },
        allowedTargets: null,
      },
    ],
    runtimeBindings: { cellRefs: {} },
  });
  document.body.innerHTML = `
    <main id="app-shell">
      <marimo-output
        id="rich-summary-output"
        value="report"
        data-marimo-studio-site="${siteId}"
      ></marimo-output>
    </main>
    <div id="runtime-root"></div>
  `;
  const host = document.querySelector<MarimoOutputElement>("marimo-output")!;
  const runtimeRoot = createRoot(document.querySelector("#runtime-root")!);
  const readOutputs = vi.fn<OutputReader>();
  await act(async () => {
    runtimeRoot.render(
      createElement(RuntimeOutputs, {
        cells: indexCells([]),
        connectionState: "OPEN",
        readOutputs,
        runtimeReady: true,
      }),
    );
  });
  const diagnostic = host.querySelector('[role="status"]');
  expect(diagnostic).not.toBeNull();
  const current = document.querySelector<HTMLElement>("#app-shell")!;
  const next = document.createElement("main");
  next.id = "app-shell";
  next.innerHTML = `
    <marimo-output
      id="rich-summary-output"
      value="missing_output"
      data-marimo-studio-site="${siteId}"
    ></marimo-output>
  `;
  prepareOutputHosts(next);

  await act(async () => {
    morphAuthoredShell(current, next);
  });

  expect(current.querySelector("marimo-output")).toBe(host);
  expect(host.querySelector('[role="status"]')).toBe(diagnostic);
  expect(host.dataset.state).toBe("error");
  expect(host.textContent).toContain('Notebook variable "missing_output" does not resolve');
  await act(async () => runtimeRoot.unmount());
});

test("reads ready rich output hosts in one bounded batch", async () => {
  const requests = [projectionRequest("report", "output"), projectionRequest("figure", "output")];
  commitRuntimeConfig(projectionRuntimeConfig(requests));
  document.body.innerHTML = `
    <marimo-output value="report" data-marimo-studio-site="${requests[0]!.siteId}"></marimo-output>
    <marimo-output value="figure" data-marimo-studio-site="${requests[1]!.siteId}"></marimo-output>
    <div id="root"></div>
  `;
  const root = createRoot(document.querySelector("#root")!);
  const readOutputs = vi.fn<OutputReader>(async (request) => ({
    outputs: Object.fromEntries(
      request.projections.map((projection, index) => [
        projection.target,
        output(projection.target, index + 1),
      ]),
    ),
    errors: {},
  }));

  await act(async () => {
    root.render(
      createElement(RuntimeOutputs, {
        cells: indexCells([runtimeCell(1, "report-cell"), runtimeCell(1, "figure-cell")]),
        connectionState: "OPEN",
        readOutputs,
        runtimeReady: true,
      }),
    );
  });
  await vi.waitFor(() => {
    expect(document.querySelector('[value="report"]')?.getAttribute("data-state")).toBe("ready");
    expect(document.querySelector('[value="figure"]')?.getAttribute("data-state")).toBe("ready");
  });

  const reads = readOutputs.mock.calls
    .map(([request]) => request)
    .filter((request) => request.projections.length > 0);
  expect(reads).toHaveLength(1);
  expect(reads[0]?.projections.map((projection) => projection.target).sort()).toEqual([
    "figure",
    "report",
  ]);
  await act(async () => root.unmount());
});

test("keeps a sibling output ready when one split leaf exceeds the response budget", async () => {
  const requests = [
    projectionRequest("oversized", "output"),
    projectionRequest("summary", "output"),
  ];
  commitRuntimeConfig(projectionRuntimeConfig(requests));
  document.body.innerHTML = `
    <marimo-output value="oversized" data-marimo-studio-site="${requests[0]!.siteId}"></marimo-output>
    <marimo-output value="summary" data-marimo-studio-site="${requests[1]!.siteId}"></marimo-output>
    <div id="root"></div>
  `;
  const root = createRoot(document.querySelector("#root")!);
  const readOutputs = vi.fn<OutputReader>(async (request): Promise<OutputReadResponse> => {
    const target = request.projections[0]?.target;
    if (request.projections.length > 1 || target === "oversized") {
      return {
        outputs: {},
        errors: {
          "*": {
            code: "response-too-large",
            message: "The output response exceeds the aggregate byte limit.",
          },
        },
      };
    }
    return target
      ? { outputs: { [target]: output(target, 1) }, errors: {} }
      : { outputs: {}, errors: {} };
  });

  await act(async () => {
    root.render(
      createElement(RuntimeOutputs, {
        cells: indexCells([runtimeCell(1, "oversized-cell"), runtimeCell(1, "summary-cell")]),
        connectionState: "OPEN",
        readOutputs,
        runtimeReady: true,
      }),
    );
  });
  await act(async () => {
    await vi.waitFor(() => {
      expect(document.querySelector('[value="oversized"]')?.getAttribute("data-state")).toBe(
        "error",
      );
      expect(document.querySelector('[value="summary"]')?.getAttribute("data-state")).toBe("ready");
    });
  });

  const oversized = document.querySelector<HTMLElement>('[value="oversized"]')!;
  const summary = document.querySelector<HTMLElement>('[value="summary"]')!;
  expect(oversized.dataset.marimoDiagnosticCode).toBe("response-too-large");
  expect(summary.dataset.outputMime).toBe("text/plain");
  await act(async () => root.unmount());
});

test.each(["__proto__", "constructor"])(
  "renders the own output record for prototype-named selector %s",
  async (selector) => {
    document.body.innerHTML = `<marimo-output value="${selector}"></marimo-output><div id="root"></div>`;
    const host = document.querySelector<MarimoOutputElement>("marimo-output")!;
    const root = createRoot(document.querySelector("#root")!);
    startRenderedViewObserver(async () => {});
    setRuntimeConnectionState("ready");
    const response = parseOutputReadResponse({
      outputs: Object.fromEntries([[selector, output(selector, 1)]]),
      errors: {},
    });
    const readOutputs = vi.fn<OutputReader>().mockResolvedValue(response);

    await act(async () => {
      root.render(
        createElement(OutputPortal, {
          activeProjections: [
            {
              ...projectionRequest(selector, "output"),
              siteId: "site:output:prototype",
            },
          ],
          projection: resolvedOutput(selector, `cell:v1:${selector}`, "source-cell", selector),
          resolutionFailure: undefined,
          connectionState: "OPEN",
          developer: true,
          host,
          readOutputs,
          runtimeReady: true,
          cell: runtimeCell(1),
        }),
      );
      await Promise.resolve();
    });

    expect(host.dataset.state).toBe("ready");
    expect(host.dataset.outputMime).toBe("text/plain");
    await act(async () => root.unmount());
  },
);

test("treats inherited output response properties as absent", async () => {
  const selector = "constructor";
  document.body.innerHTML = `<marimo-output value="${selector}"></marimo-output><div id="root"></div>`;
  const host = document.querySelector<MarimoOutputElement>("marimo-output")!;
  const root = createRoot(document.querySelector("#root")!);
  startRenderedViewObserver(async () => {});
  setRuntimeConnectionState("ready");
  const readOutputs = vi.fn<OutputReader>().mockResolvedValue({ outputs: {}, errors: {} });

  await act(async () => {
    root.render(
      createElement(OutputPortal, {
        activeProjections: [
          {
            ...projectionRequest(selector, "output"),
            siteId: "site:output:prototype",
          },
        ],
        projection: resolvedOutput(selector, `cell:v1:${selector}`, "source-cell", selector),
        resolutionFailure: undefined,
        connectionState: "OPEN",
        developer: true,
        host,
        readOutputs,
        runtimeReady: true,
        cell: runtimeCell(1),
      }),
    );
    await Promise.resolve();
  });

  expect(host.dataset.state).toBe("error");
  expect(host.dataset.marimoDiagnosticCode).toBe("invalid-output-response");
  await act(async () => root.unmount());
});
