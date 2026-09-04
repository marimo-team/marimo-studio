import type {
  CellConsoleOutput,
  CellId,
  CellOutput,
} from "@marimo-studio/marimo-frontend/cell-presentation";
import type {
  PreparedPresentationHandle,
  PreparedThemeSource,
} from "@marimo-studio/marimo-frontend/prepared-presentation";

import { ProjectedCellPresentation } from "@marimo-studio/marimo-frontend/cell-presentation";
import { mountPreparedPresentation } from "@marimo-studio/marimo-frontend/prepared-presentation";
import { act, createElement } from "react";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { createPreparedModelGraph } from "../src/prepared/index.ts";

const presentation = {
  appConfig: {},
  configOverrides: {},
  userConfig: {},
};

const theme: PreparedThemeSource = {
  current: () => "light",
  subscribe: () => () => {},
};

const mounted: PreparedPresentationHandle[] = [];

// SAFETY: The fixture uses one nonempty stable identifier for a projected runtime cell.
const cellId = "projected-cell" as CellId;

const consoleOutput = (
  channel: CellConsoleOutput["channel"],
  data: string,
  response?: string,
): CellConsoleOutput => {
  // SAFETY: This fixture supplies the complete wire shape used by projected console rendering.
  return {
    channel,
    data,
    mimetype: "text/plain",
    response,
    timestamp: 1,
  } as CellConsoleOutput;
};

const publishedOutput = (data: string): CellOutput => ({
  channel: "output",
  data,
  mimetype: "text/plain",
  timestamp: 1,
});

const mount = (consoleOutputs: CellConsoleOutput[], onSubmitStdin = vi.fn()) => {
  const root = document.createElement("div");
  document.body.append(root);
  const handle = mountPreparedPresentation({
    createModelGraph: createPreparedModelGraph,
    presentation,
    root,
    theme,
    render: createElement(ProjectedCellPresentation, {
      accessibleName: "Forecast parameters",
      cellId,
      cellName: "parameters",
      consoleOutputs,
      interrupted: false,
      loading: false,
      output: publishedOutput("published output"),
      stale: false,
      onSubmitStdin,
    }),
  });
  mounted.push(handle);
  return { onSubmitStdin, root };
};

afterEach(async () => {
  await Promise.allSettled(mounted.splice(0).map((handle) => handle.dispose()));
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

test("projected cells omit editor affordances while retaining published channels", () => {
  const { root } = mount([consoleOutput("marimo-error", "calculation failed")]);
  const projected = root.querySelector<HTMLElement>("[data-marimo-presentation='projected-cell']");

  expect(projected?.getAttribute("aria-label")).toBe("Forecast parameters");
  expect(projected?.getAttribute("role")).toBe("group");
  expect(root.textContent).toContain("calculation failed");
  expect(root.textContent).toContain("published output");
  expect(root.querySelector("[contenteditable='true']")).toBeNull();
  expect(root.querySelector("[data-testid='console-output-area']")?.getAttribute("tabindex")).toBe(
    null,
  );
});

test("projected stdin uses the host label and submits through the runtime callback", async () => {
  const onSubmitStdin = vi.fn();
  const { root } = mount([consoleOutput("stdin", "Your region?")], onSubmitStdin);
  const input = root.querySelector<HTMLInputElement>("[data-testid='console-input']");

  expect(input?.getAttribute("aria-label")).toBe("Forecast parameters input");
  await act(async () => {
    if (!input) {
      throw new Error("Expected projected stdin to render an input");
    }
    const value = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    value?.call(input, "west");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    if (!input) {
      throw new Error("Expected projected stdin to render an input");
    }
    input.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" }));
  });

  expect(onSubmitStdin).toHaveBeenCalledWith("west", 0);
});
