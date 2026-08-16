import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { parseErrorResponse } from "../src/errors.ts";
import {
  parseValueReadResponse,
  valueReadRequestSchema,
  valueReadResponseSchema,
} from "../src/value-read.ts";
import { parseCreatedView, parseDeletedView, parseViewList } from "../src/views.ts";

test("view responses validate list, create, and delete envelopes", () => {
  const views = { schema: 1, default_view: "dashboard", views: ["dashboard", "report"] };

  assert.deepEqual(parseViewList(views), views);
  assert.deepEqual(parseCreatedView({ schema: 1, name: "report" }), {
    schema: 1,
    name: "report",
  });
  assert.deepEqual(parseDeletedView({ ...views, name: "report" }), { ...views, name: "report" });

  assert.throws(() => parseViewList({ ...views, default_view: "missing" }));
  assert.throws(() => parseCreatedView({ schema: 1, name: 42 }));
  assert.throws(() => parseDeletedView(views));
});

test("value responses validate errors before presentation consumes them", () => {
  const response = {
    values: { "context.total": 42 },
    errors: {
      "context.missing": {
        code: "missing-key",
        message: "The selected key is unavailable.",
        hint: "Choose another selector.",
      },
    },
  };

  assert.deepEqual(parseValueReadResponse(response), response);
  assert.throws(() =>
    parseValueReadResponse({ values: {}, errors: { broken: { code: 42, message: "bad" } } }),
  );
  assert.throws(() =>
    valueReadResponseSchema.parse({ values: { missing: undefined }, errors: {} }),
  );
});

test("value requests identify their presentation revision", () => {
  const request = { revision: "presentation-revision", selectors: ["context.total"] };

  assert.deepEqual(valueReadRequestSchema.parse(request), request);
  assert.throws(() => valueReadRequestSchema.parse({ selectors: ["context.total"] }));
  assert.throws(() => valueReadRequestSchema.parse({ revision: "", selectors: [] }));
});

test("error responses keep recognized diagnostic fields", () => {
  assert.deepEqual(
    parseErrorResponse({
      error: "source-conflict",
      message: "The source changed.",
      hint: "Reload the source.",
      transient: true,
      revision: "r2",
      ignored: 42,
    }),
    {
      error: "source-conflict",
      message: "The source changed.",
      hint: "Reload the source.",
      transient: true,
      revision: "r2",
    },
  );
  const partial = parseErrorResponse({ message: 42, revision: "r3" });

  assert.equal(partial.revision, "r3");
  assert.equal(partial.message ?? "fallback", "fallback");
});
