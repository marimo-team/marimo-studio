import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  MAX_OUTPUT_SELECTORS,
  outputReadRequestSchema,
  parseOutputReadResponse,
} from "../src/output-read.ts";

test("output requests require rendered selectors to remain active", () => {
  assert.throws(() =>
    outputReadRequestSchema.parse({
      revision: "revision",
      selectors: ["df"],
      activeSelectors: [],
    }),
  );
});

test("output requests enforce the authored selector limit", () => {
  const selectors = Array.from({ length: MAX_OUTPUT_SELECTORS }, (_, index) => `output_${index}`);
  assert.doesNotThrow(() =>
    outputReadRequestSchema.parse({
      revision: "revision",
      selectors,
      activeSelectors: selectors,
    }),
  );
  assert.throws(() =>
    outputReadRequestSchema.parse({
      revision: "revision",
      selectors: [...selectors, "output_100"],
      activeSelectors: [...selectors, "output_100"],
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

  assert.deepEqual(parseOutputReadResponse(response), response);
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
