import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, test } from "vite-plus/test";

import type { RuntimeCell } from "../src/runtime/runtime-cell.ts";

import { getRenderInputReader } from "../src/renders/inputs.ts";
import { commitRuntimeConfig } from "../src/runtime-config";
import { type RuntimeRenderReader, useRenderInputs } from "../src/runtime/render-inputs.ts";
import { runtimeCellFixture } from "./runtime-cell-fixture";
import { runtimeConfig } from "./runtime-fixtures";

const reads = { revision: "revision", values: [], outputs: [], cells: [] };

const Harness = (props: { cells: readonly RuntimeCell[]; read: RuntimeRenderReader }) => {
  useRenderInputs(props.cells, true, props.read);
  return null;
};

const mount = (read: RuntimeRenderReader) => {
  document.body.innerHTML = '<div id="root"></div>';
  const root = createRoot(document.querySelector("#root")!);
  const show = (cells: readonly RuntimeCell[]) =>
    act(async () => {
      root.render(createElement(Harness, { cells, read }));
    });
  return { root, show };
};

const idle = (output: string) =>
  runtimeCellFixture({
    status: "idle",
    output: { channel: "output", mimetype: "text/plain", data: output, timestamp: 0 },
  });

afterEach(() => {
  document.body.innerHTML = "";
});

test("a browser read that spans a notebook run reports the notebook unsettled", async () => {
  commitRuntimeConfig(runtimeConfig());
  let finish = () => {};
  const read: RuntimeRenderReader = () =>
    new Promise((resolve) => {
      finish = () => resolve({ values: { total: 1 }, outputs: {} });
    });
  const { root, show } = mount(read);
  await show([idle("first")]);

  const pending = getRenderInputReader()!("main.typ", reads, new AbortController().signal);
  await show([runtimeCellFixture({ status: "running" })]);
  await show([idle("second")]);
  finish();

  await expect(pending).resolves.toBeUndefined();
  await act(async () => root.unmount());
});

test("a browser read between two runs returns the render's inputs", async () => {
  commitRuntimeConfig(runtimeConfig());
  const read: RuntimeRenderReader = () => Promise.resolve({ values: { total: 1 }, outputs: {} });
  const { root, show } = mount(read);
  await show([idle("first")]);

  const inputs = await getRenderInputReader()!("main.typ", reads, new AbortController().signal);

  expect(inputs).toEqual({ values: { total: 1 }, outputs: {}, cells: {} });
  await act(async () => root.unmount());
});
