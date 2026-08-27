import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { outputReadRequestSchema, parseOutputReadResponse } from "../src/output-read.ts";
import { projectionRequest } from "./fixtures.ts";

test("output requests require rendered selectors to remain active", () => {
  assert.throws(() =>
    outputReadRequestSchema.parse({
      revision: "revision",
      projections: [projectionRequest("df", "projection-df")],
      activeProjections: [],
    }),
  );
});

test("output requests enforce the authored selector limit", () => {
  const projections = Array.from({ length: 100 }, (_, index) =>
    projectionRequest(`output_${index}`, `projection-${index}`),
  );
  assert.doesNotThrow(() =>
    outputReadRequestSchema.parse({
      revision: "revision",
      projections,
      activeProjections: projections,
    }),
  );
  assert.throws(() =>
    outputReadRequestSchema.parse({
      revision: "revision",
      projections: [...projections, projectionRequest("output_100", "projection-100")],
      activeProjections: [...projections, projectionRequest("output_100", "projection-100")],
    }),
  );
});

test("output responses preserve native MIME records", () => {
  const response = {
    outputs: {
      df: {
        ownerCellId: "__marimo_studio_output_df",
        mimetype: "text/html",
        data: "<marimo-ui-element></marimo-ui-element>",
        timestamp: 1_786_343_200,
        resetUiObjectIds: [],
      },
    },
    errors: {},
  };

  const parsed = parseOutputReadResponse(response);
  assert.equal(Object.getPrototypeOf(parsed.outputs), null);
  assert.equal(Object.getPrototypeOf(parsed.errors), null);
  assert.deepEqual(parsed.outputs.df, response.outputs.df);
});

test("output responses preserve prototype-named selectors as own records", () => {
  const selectors = ["__proto__", "constructor"];
  const parsed = parseOutputReadResponse({
    outputs: Object.fromEntries(
      selectors.map((selector, index) => [
        selector,
        {
          ownerCellId: `projected-${index}`,
          mimetype: "text/plain",
          data: selector,
          timestamp: index,
          resetUiObjectIds: [],
        },
      ]),
    ),
    errors: {},
  });

  selectors.forEach((selector) => {
    assert.equal(Object.hasOwn(parsed.outputs, selector), true);
    assert.equal(parsed.outputs[selector]?.data, selector);
  });
  const absent = parseOutputReadResponse({ outputs: {}, errors: {} });
  selectors.forEach((selector) => assert.equal(Object.hasOwn(absent.outputs, selector), false));
});

test("output responses reject malformed native records", () => {
  assert.throws(() =>
    parseOutputReadResponse({
      outputs: {
        df: {
          ownerCellId: "__marimo_studio_output_df",
          mimetype: "text/html",
          data: {},
          timestamp: "now",
          resetUiObjectIds: [],
        },
      },
      errors: {},
    }),
  );
});

test("output responses reject UI resets owned by another cell", () => {
  assert.throws(() =>
    parseOutputReadResponse({
      outputs: {
        df: {
          ownerCellId: "__marimo_studio_output_df",
          mimetype: "text/html",
          data: "<marimo-ui-element></marimo-ui-element>",
          timestamp: 1,
          resetUiObjectIds: ["source-cell-0"],
        },
      },
      errors: {},
    }),
  );
});
