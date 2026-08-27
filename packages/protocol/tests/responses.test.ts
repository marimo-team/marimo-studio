import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { parseErrorResponse } from "../src/errors.ts";
import { PROJECTION_UNPAIRED_SURROGATE_CODE, projectionRequestSchema } from "../src/projections.ts";
import {
  parseValueReadResponse,
  valueReadRequestSchema,
  valueReadResponseSchema,
} from "../src/value-read.ts";
import {
  type CreatedView,
  parseCreatedView,
  parseDeletedView,
  parseViewList,
  type ViewList,
} from "../src/views.ts";
import { componentStarter, projectionRequest, starter } from "./fixtures.ts";

test("view responses validate list, create, and delete envelopes", () => {
  const views: ViewList = {
    schema: 1,
    default_view: "dashboard",
    default_starter: "marimo-studio/vanilla:default",
    views: [{ name: "dashboard" }, { name: "report" }],
    starters: [componentStarter, starter],
  };
  const created: CreatedView = {
    schema: 2,
    name: "report",
  };
  const deleted = {
    ...views,
    views: [views.views[0]!],
    name: "report",
  };

  assert.deepEqual(parseViewList(views), views);
  assert.deepEqual(parseCreatedView(created), created);
  assert.deepEqual(parseDeletedView(deleted), deleted);

  assert.throws(() => parseViewList({ ...views, default_view: "missing" }));
  assert.throws(() => parseViewList({ ...views, default_view: "" }));
  assert.throws(() => parseViewList({ ...views, default_starter: "missing" }));
  assert.throws(() => parseViewList({ ...views, unexpected: true }));
  assert.throws(() => parseViewList({ ...views, views: [views.views[0], views.views[0]] }));
  assert.throws(() =>
    parseViewList({ ...views, starters: [views.starters[0], views.starters[0]] }),
  );
  assert.throws(() =>
    parseViewList({ ...views, views: [{ ...views.views[0], name: "Bad View" }] }),
  );
  assert.throws(() => parseCreatedView({ schema: 1, name: 42 }));
  assert.throws(() => parseCreatedView({ ...created, unexpected: true }));
  assert.throws(() => parseDeletedView(views));
  assert.throws(() => parseDeletedView({ ...deleted, default_view: "" }));
  assert.throws(() =>
    parseDeletedView({
      ...deleted,
      default_view: "dashboard",
      views: [],
    }),
  );
  assert.throws(() => parseDeletedView({ ...views, name: "dashboard" }));
  assert.throws(() =>
    parseDeletedView({
      ...deleted,
      starters: [views.starters[0], views.starters[0]],
    }),
  );
  assert.throws(() => parseDeletedView({ ...deleted, unexpected: true }));
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

  const parsed = parseValueReadResponse(response);
  assert.equal(Object.getPrototypeOf(parsed.values), null);
  assert.equal(Object.getPrototypeOf(parsed.errors), null);
  assert.equal(parsed.values["context.total"], 42);
  assert.deepEqual(parsed.errors["context.missing"], response.errors["context.missing"]);
  assert.throws(() =>
    parseValueReadResponse({ values: {}, errors: { broken: { code: 42, message: "bad" } } }),
  );
  assert.throws(() =>
    valueReadResponseSchema.parse({ values: { missing: undefined }, errors: {} }),
  );
});

test("value responses preserve prototype-named selectors as own records", () => {
  const selectors = ["__proto__", "constructor"];
  const parsed = parseValueReadResponse({
    values: Object.fromEntries(selectors.map((selector, index) => [selector, index])),
    errors: {},
  });

  selectors.forEach((selector, index) => {
    assert.equal(Object.hasOwn(parsed.values, selector), true);
    assert.equal(parsed.values[selector], index);
  });
  const absent = parseValueReadResponse({ values: {}, errors: {} });
  selectors.forEach((selector) => assert.equal(Object.hasOwn(absent.values, selector), false));
});

test("value requests identify their presentation revision", () => {
  const request = {
    revision: "presentation-revision",
    projections: [projectionRequest("context.total")],
  };

  assert.deepEqual(valueReadRequestSchema.parse(request), request);
  assert.throws(() => valueReadRequestSchema.parse({ projections: request.projections }));
  assert.throws(() => valueReadRequestSchema.parse({ revision: "", projections: [] }));
});

test.each([
  ["target", "\uD800"],
  ["instanceId", "\uDFFF"],
] as const)("projection requests reject an unpaired surrogate in %s", (field, surrogate) => {
  const request = projectionRequest("context.total");
  const result = projectionRequestSchema.safeParse({
    ...request,
    [field]: surrogate,
  });

  assert.equal(result.success, false);
  if (!result.success) {
    assert.equal(result.error.issues[0]?.message, PROJECTION_UNPAIRED_SURROGATE_CODE);
  }
});

test("projection requests retain valid surrogate pairs", () => {
  const request = projectionRequest('context["😀"]');

  assert.deepEqual(projectionRequestSchema.parse(request), request);
});

test("error responses keep recognized diagnostic fields", () => {
  assert.deepEqual(
    parseErrorResponse({
      error: "source-conflict",
      message: "The source changed.",
      hint: "Reload the source.",
      transient: true,
      revision: "r2",
      external_recovery: "/workspace/.source-recovery",
      ignored: 42,
    }),
    {
      error: "source-conflict",
      message: "The source changed.",
      hint: "Reload the source.",
      transient: true,
      revision: "r2",
      external_recovery: "/workspace/.source-recovery",
    },
  );
  const partial = parseErrorResponse({ message: 42, revision: "r3" });

  assert.equal(partial.revision, "r3");
  assert.equal(partial.message ?? "fallback", "fallback");
});
