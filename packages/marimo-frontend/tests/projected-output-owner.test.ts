// @vitest-environment jsdom

import { notebookAtom } from "@marimo-team/frontend/unstable_internal/core/cells/cells";
import { store } from "@marimo-team/frontend/unstable_internal/core/state/jotai";
import { Provider } from "jotai";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { ProjectedOutputArea } from "../src/projected-output.tsx";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

test("projected output owners require own notebook state entries", async () => {
  store.set(notebookAtom, (state) => {
    const cellData = { ...state.cellData };
    const cellRuntime = { ...state.cellRuntime };
    Reflect.deleteProperty(cellData, "toString");
    Reflect.deleteProperty(cellRuntime, "toString");
    return { ...state, cellData, cellRuntime };
  });
  const target = document.createElement("div");
  document.body.append(target);
  const root = createRoot(target);

  await act(async () => {
    root.render(
      createElement(
        Provider,
        { store },
        createElement(ProjectedOutputArea, {
          output: {
            ownerCellId: "toString",
            channel: "output",
            mimetype: "text/plain",
            data: "reserved owner",
            timestamp: 1,
            resetUiObjectIds: [],
          },
          stale: false,
        }),
      ),
    );
  });
  await vi.waitFor(() => {
    const notebook = store.get(notebookAtom);
    expect(Object.hasOwn(notebook.cellData, "toString")).toBe(true);
    expect(Object.hasOwn(notebook.cellRuntime, "toString")).toBe(true);
  });

  await act(async () => root.unmount());
});

test("projected function callers carry active and rendered revisions", async () => {
  const target = document.createElement("div");
  document.body.append(target);
  const root = createRoot(target);
  const ownerCellId = "projected-owner";
  await act(async () => {
    root.render(
      createElement(
        Provider,
        { store },
        createElement(ProjectedOutputArea, {
          functionRequestScope: {
            activeOwner: '["revision-b",2]',
            outputOwner: '["revision-a",1]',
          },
          output: {
            ownerCellId,
            channel: "output",
            mimetype: "text/plain",
            data: "projected output",
            timestamp: 1,
            resetUiObjectIds: [],
          },
          stale: true,
        }),
      ),
    );
  });

  const output = target.querySelector("[data-marimo-studio-projected-output]");
  expect(output?.getAttribute("data-marimo-studio-active-projection-owner")).toBe(
    '["revision-b",2]',
  );
  expect(output?.getAttribute("data-marimo-studio-output-projection-owner")).toBe(
    '["revision-a",1]',
  );

  await act(async () => root.unmount());
});
