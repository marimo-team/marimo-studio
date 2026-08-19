import type { OutputReadResponse, RenderedOutput } from "@marimo-studio/protocol/output-read";

import { act, createElement, type ComponentProps } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, expect, test, vi } from "vite-plus/test";

import type { MarimoOutputElement } from "../src/outputs/host";
import type { OutputReader } from "../src/outputs/reader";

import { registerMarimoOutputElement } from "../src/outputs/host";
import {
  setRuntimeConnectionState,
  startRenderedViewObserver,
  stopRenderedViewObserver,
} from "../src/rendered-view-observer";
import { OutputPortal } from "../src/runtime/outputs/OutputPortal";
import { runtimeCellFixture } from "./runtime-cell-fixture";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "revision-a",
  runtime: "server",
};

beforeAll(() => registerMarimoOutputElement());

afterEach(() => {
  vi.clearAllMocks();
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
    activeSelectors: ["report"],
    binding: { variable: "report", cell: { kind: "id" as const, value: "source-cell" } },
    connectionState: "OPEN",
    developer: true,
    host,
    readOutputs,
    revision: "revision-a",
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
    root.render(
      createElement(OutputPortal, {
        ...props,
        activeSelectors: ["report", "other"],
        cell: runtimeCell(2),
        revision: "revision-b",
      }),
    );
  });
  expect(readOutputs).toHaveBeenCalledTimes(2);
  expect(host.dataset.state).toBe("ready");
  expect(host.dataset.runtimeCellId).toBe("source-cell");
  expect(host.dataset.outputMime).toBe("text/plain");

  await act(async () => root.unmount());
});

test("clears prior projection metadata when its binding changes", async () => {
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
  const props: Omit<ComponentProps<typeof OutputPortal>, "binding" | "cell"> = {
    activeSelectors: ["report"],
    connectionState: "OPEN",
    developer: true,
    host,
    readOutputs,
    revision: "revision-a",
    runtimeReady: true,
  };

  await act(async () => {
    root.render(
      createElement(OutputPortal, {
        ...props,
        binding: { variable: "first", cell: { kind: "id", value: "source-cell" } },
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
        binding: { variable: "second", cell: { kind: "id", value: "next-cell" } },
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
