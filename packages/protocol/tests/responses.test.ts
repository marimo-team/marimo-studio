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
  createViewRequestSchema,
  deleteViewRequestSchema,
  type CreatedView,
  parseCreatedView,
  parseDeletedView,
  parseViewList,
  type ViewList,
} from "../src/views.ts";
import { componentStarter, projectionRequest, starter } from "./fixtures.ts";

test("view responses validate list, create, and delete envelopes", () => {
  const dashboardGeneration = "a".repeat(64);
  const reportGeneration = "b".repeat(64);
  const views: ViewList = {
    schema: 1,
    generation: "c".repeat(64),
    default_view: "dashboard",
    default_starter: "marimo-studio/vanilla:default",
    views: [
      { generation: dashboardGeneration, name: "dashboard" },
      { generation: reportGeneration, name: "report" },
    ],
    starters: [componentStarter, starter],
  };
  const created: CreatedView = {
    schema: 1,
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
  assert.deepEqual(
    parseDeletedView({ ...deleted, cleanup: "/tmp/delete-view" }).cleanup,
    "/tmp/delete-view",
  );
  assert.deepEqual(
    createViewRequestSchema.parse({
      catalog_generation: views.generation,
      name: "report",
      starter: "marimo-studio/vanilla:default",
    }),
    {
      catalog_generation: views.generation,
      name: "report",
      starter: "marimo-studio/vanilla:default",
    },
  );
  assert.deepEqual(
    deleteViewRequestSchema.parse({
      catalog_generation: views.generation,
      name: "report",
      view_generation: reportGeneration,
    }),
    {
      catalog_generation: views.generation,
      name: "report",
      view_generation: reportGeneration,
    },
  );

  assert.throws(() => parseViewList({ ...views, default_view: "missing" }));
  assert.throws(() => parseViewList({ ...views, default_view: "" }));
  assert.throws(() => parseViewList({ ...views, default_starter: "missing" }));
  assert.throws(() => parseViewList({ ...views, generation: "stale" }));
  assert.throws(() => parseViewList({ ...views, unexpected: true }));
  assert.throws(() => parseViewList({ ...views, views: [views.views[0], views.views[0]] }));
  assert.throws(() =>
    parseViewList({ ...views, starters: [views.starters[0], views.starters[0]] }),
  );
  assert.throws(() =>
    parseViewList({ ...views, views: [{ ...views.views[0], name: "Bad View" }] }),
  );
  assert.throws(() =>
    parseViewList({ ...views, views: [{ ...views.views[0], generation: "stale" }] }),
  );
  assert.throws(() =>
    createViewRequestSchema.parse({
      catalog_generation: views.generation,
      name: "report",
      starter: "vanilla",
    }),
  );
  assert.throws(() =>
    deleteViewRequestSchema.parse({
      catalog_generation: views.generation,
      name: "report",
    }),
  );
  assert.throws(() =>
    deleteViewRequestSchema.parse({
      catalog_generation: views.generation,
      name: "report",
      view_generation: reportGeneration,
      extra: true,
    }),
  );
  assert.throws(() => parseCreatedView({ schema: 2, name: 42 }));
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
  assert.throws(() => parseDeletedView({ ...deleted, cleanup: "" }));
});

test("value responses validate errors before presentation consumes them", () => {
  const fingerprint = `sha256:${"0".repeat(64)}`;
  const response = {
    values: {
      "context.total": {
        codec: "json-v1",
        fingerprint,
        value: 42,
      },
    },
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
  assert.deepEqual(parsed.values["context.total"], response.values["context.total"]);
  assert.deepEqual(parsed.errors["context.missing"], response.errors["context.missing"]);
  assert.throws(() =>
    parseValueReadResponse({ values: {}, errors: { broken: { code: 42, message: "bad" } } }),
  );
  assert.throws(() =>
    valueReadResponseSchema.parse({ values: { missing: undefined }, errors: {} }),
  );
  assert.throws(() => valueReadResponseSchema.parse({ values: { total: 42 }, errors: {} }));
  assert.throws(() =>
    valueReadResponseSchema.parse({
      values: {
        total: { codec: "json-v1", fingerprint: "sha256:invalid", value: 42 },
      },
      errors: {},
    }),
  );
  assert.throws(() =>
    valueReadResponseSchema.parse({
      values: {
        table: {
          codec: "arrow-ipc-v1",
          fingerprint,
          dataUrl: "/@file/table.arrow",
          byteLength: 0,
        },
      },
      errors: {},
    }),
  );
  assert.throws(() =>
    valueReadResponseSchema.parse({
      values: {
        table: {
          codec: "unknown-v1",
          fingerprint,
          value: 42,
        },
      },
      errors: {},
    }),
  );
});

test("value responses preserve prototype-named selectors as own records", () => {
  const selectors = ["__proto__", "constructor"];
  const parsed = parseValueReadResponse({
    values: Object.fromEntries(
      selectors.map((selector, index) => [
        selector,
        {
          codec: "json-v1",
          fingerprint: `sha256:${String(index).repeat(64)}`,
          value: index,
        },
      ]),
    ),
    errors: {},
  });

  selectors.forEach((selector, index) => {
    assert.equal(Object.hasOwn(parsed.values, selector), true);
    assert.equal(parsed.values[selector]?.codec, "json-v1");
    assert.equal(parsed.values[selector]?.value, index);
  });
  const absent = parseValueReadResponse({ values: {}, errors: {} });
  selectors.forEach((selector) => assert.equal(Object.hasOwn(absent.values, selector), false));
});

test("value requests identify their presentation revision", () => {
  const projection = projectionRequest("context.total");
  const request = {
    revision: "presentation-revision",
    projections: [projection],
    activeProjections: [projection],
  };

  assert.deepEqual(valueReadRequestSchema.parse(request), request);
  assert.throws(() =>
    valueReadRequestSchema.parse({
      projections: request.projections,
      activeProjections: request.activeProjections,
    }),
  );
  assert.throws(() =>
    valueReadRequestSchema.parse({
      revision: "",
      projections: [],
      activeProjections: [],
    }),
  );
  assert.throws(() =>
    valueReadRequestSchema.parse({
      ...request,
      activeProjections: [],
    }),
  );
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
