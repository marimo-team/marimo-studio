import type { EmbeddedFunctionRequest } from "@marimo-studio/marimo-frontend/embedded-runtime";

import { expect, test, vi } from "vite-plus/test";

import type { RenderReads } from "../src/renders/inputs.ts";
import type { ValueReader } from "../src/values/reader.ts";

import { createWasmOutputReader, createWasmOutputRequest } from "../src/outputs/wasm.ts";
import { RenderInputError } from "../src/renders/inputs.ts";
import { createWasmRenderReader } from "../src/runtime/wasm-render-inputs.ts";

const reads: RenderReads = {
  revision: "presentation-revision",
  values: [{ siteId: "read-total", instanceId: "render:figure.py:read-total", target: "total" }],
  outputs: [{ siteId: "read-chart", instanceId: "render:figure.py:read-chart", target: "chart" }],
  cells: [
    { siteId: "read-summary", instanceId: "render:figure.py:read-summary", target: "summary" },
  ],
};

const chart = {
  ownerCellId: "__marimo_studio_output_chart",
  mimetype: "image/png",
  data: "data:image/png;base64,AA==",
  timestamp: 1,
  resetUiObjectIds: [],
};

const notebook = () => {
  const steps: string[] = [];
  const invoke = vi.fn(async ({ args }: EmbeddedFunctionRequest) => {
    const releasing = Array.isArray(args.projections) && args.projections.length === 0;
    steps.push(releasing ? "release" : "outputs");
    return {
      found: true,
      status: { code: "ok", message: null },
      return_value: {
        outputs: Object.fromEntries(releasing ? [] : [["chart", chart]]),
        errors: {},
      },
    };
  });
  const readValues = vi.fn<ValueReader>(async () => {
    steps.push("values");
    return {
      values: {
        total: { codec: "json-v1", fingerprint: `sha256:${"a".repeat(64)}`, value: [{ n: 3 }] },
      },
      errors: {},
    };
  });
  const read = createWasmRenderReader({
    sessionId: "s_page01",
    readValues,
    readOutputs: (consumerId) =>
      createWasmOutputReader(
        async () => {},
        createWasmOutputRequest(consumerId, invoke, async () => {}),
        (response) => response,
      ),
    revision: () => "presentation-revision",
    prepareCells: async ({ projections }) => {
      steps.push(`cells:${projections.map(({ target }) => target).join(",")}`);
    },
  });
  return { steps, invoke, readValues, read };
};

test("a render reads outputs as its own bridge consumer after running its cells", async () => {
  const { steps, invoke, readValues, read } = notebook();

  const inputs = await read("figure.py", reads, new AbortController().signal);

  expect(steps.slice(0, 3)).toEqual(["cells:summary", "values", "outputs"]);
  expect(invoke).toHaveBeenCalledWith(
    expect.objectContaining({
      functionName: "render_values",
      args: expect.objectContaining({ consumer_id: "s_page01:render:figure.py" }),
    }),
  );
  expect(readValues).toHaveBeenCalledWith(
    {
      revision: "presentation-revision",
      projections: reads.values,
      activeProjections: reads.values,
    },
    expect.any(AbortSignal),
  );
  expect(inputs).toEqual({
    values: { total: [{ n: 3 }] },
    outputs: { chart: { mimetype: "image/png", data: "data:image/png;base64,AA==" } },
  });
});

test("a render releases its bridge consumer with an empty read once it has the output bytes", async () => {
  const { steps, invoke, read } = notebook();

  await read("figure.py", reads, new AbortController().signal);

  expect(steps.slice(2)).toEqual(["outputs", "release"]);
  expect(invoke).toHaveBeenLastCalledWith(
    expect.objectContaining({
      functionName: "render_values",
      args: {
        revision: "presentation-revision",
        projections: [],
        active_projections: [],
        consumer_id: "s_page01:render:figure.py",
      },
    }),
  );
});

test("a value without a JSON form fails the render as the Python runtime reports it", async () => {
  const read = createWasmRenderReader({
    sessionId: "s_page01",
    readValues: async () => ({
      values: {},
      errors: {
        total: { code: "not-json-serializable", message: "Selector 'total' has no JSON form." },
        later: { code: "value-path-unavailable", message: "Selector 'later' is undefined." },
      },
    }),
    readOutputs: () => async () => ({ outputs: {}, errors: {} }),
    revision: () => "presentation-revision",
    prepareCells: async () => {},
  });

  await expect(read("figure.py", reads, new AbortController().signal)).rejects.toThrow(
    RenderInputError,
  );
  await expect(read("figure.py", reads, new AbortController().signal)).rejects.toMatchObject({
    diagnostics: [
      expect.objectContaining({
        code: "render-value-not-json",
        message: "Selector 'total' has no JSON form.",
      }),
    ],
  });
});
