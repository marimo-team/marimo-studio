// @vitest-environment jsdom

import type {
  ModelState,
  WidgetModelId,
} from "@marimo-team/frontend/unstable_internal/plugins/impl/anywidget/types";

import { WIDGET_REGISTRY } from "@marimo-team/frontend/unstable_internal/plugins/impl/anywidget/registry";
import assert from "node:assert/strict";
import { afterEach, test, vi } from "vite-plus/test";

import type {
  PreparedModelLifecycleHandle,
  PreparedModelLifecycleNotification,
} from "../src/prepared-models.ts";

import { createPreparedModelLifecycle } from "../src/prepared-models.ts";

// SAFETY: The test observes the browser global owned by the prepared model facade.
const browser = globalThis as typeof globalThis & {
  __MARIMO_STATIC__?: { readonly files: Readonly<Record<string, string>> };
};

let lifecycle: PreparedModelLifecycleHandle | undefined;

const modelId = (value: string): WidgetModelId => {
  assert.ok(value.length > 0);
  // SAFETY: The assertion above matches Marimo's WidgetModelId predicate.
  return value as WidgetModelId;
};

const openNotification = (
  id: WidgetModelId,
  state: ModelState,
  esm_spec: { readonly url: string; readonly hash: string } | null = null,
): PreparedModelLifecycleNotification => ({
  model_id: id,
  message: {
    method: "open",
    state,
    buffer_paths: [],
    buffers: [],
    esm_spec,
  },
});

afterEach(async () => {
  await lifecycle?.dispose();
  lifecycle = undefined;
  vi.restoreAllMocks();
  delete browser.__MARIMO_STATIC__;
});

test("native model checkpoints restore browser state and close retired models", async () => {
  lifecycle = createPreparedModelLifecycle();
  const id = modelId("prepared-native-model");
  const staged = await lifecycle.replace({
    files: {},
    modelNotifications: [openNotification(id, { value: 7 })],
  });
  await staged.commit();
  const model = WIDGET_REGISTRY.getModelSync(id);
  assert.ok(model);
  model.set("value", 8);
  const checkpoint = lifecycle.snapshot();
  model.set("value", 9);

  await (await lifecycle.replace(checkpoint)).commit();

  assert.equal(WIDGET_REGISTRY.getModelSync(id), model);
  assert.equal(model.get("value"), 8);
  await (await lifecycle.replace({ files: {}, modelNotifications: [] })).commit();
  assert.equal(WIDGET_REGISTRY.getModelSync(id), undefined);
});

test("native model replay preserves cross-model update and custom-message order", async () => {
  lifecycle = createPreparedModelLifecycle();
  const first = modelId("prepared-order-first");
  const second = modelId("prepared-order-second");
  const opened = [openNotification(first, { value: 0 }), openNotification(second, { value: 0 })];
  await (await lifecycle.replace({ files: {}, modelNotifications: opened })).commit();
  const firstModel = WIDGET_REGISTRY.getModelSync(first);
  const secondModel = WIDGET_REGISTRY.getModelSync(second);
  assert.ok(firstModel);
  assert.ok(secondModel);
  const observed: unknown[] = [];
  firstModel.on("msg:custom", () => observed.push(["first", secondModel.get("value")]));
  secondModel.on("msg:custom", () => observed.push(["second", firstModel.get("value")]));
  const notifications: PreparedModelLifecycleNotification[] = [
    ...opened,
    {
      model_id: second,
      message: { method: "update", state: { value: 2 }, buffer_paths: [], buffers: [] },
    },
    { model_id: first, message: { method: "custom", content: {}, buffers: [] } },
    {
      model_id: first,
      message: { method: "update", state: { value: 1 }, buffer_paths: [], buffers: [] },
    },
    { model_id: second, message: { method: "custom", content: {}, buffers: [] } },
  ];

  await (await lifecycle.replace({ files: {}, modelNotifications: notifications })).commit();

  assert.deepEqual(observed, [
    ["first", 2],
    ["second", 1],
  ]);
  assert.equal(WIDGET_REGISTRY.getModelSync(first), firstModel);
  assert.equal(WIDGET_REGISTRY.getModelSync(second), secondModel);
});

test("native model replacement rejects malformed lifecycle and widget modules before replay", async () => {
  lifecycle = createPreparedModelLifecycle();
  const id = modelId("prepared-invalid-model");
  await assert.rejects(
    lifecycle.replace({
      files: {},
      modelNotifications: [
        {
          model_id: id,
          message: {
            method: "update",
            state: { value: 1 },
            buffer_paths: [],
            buffers: [],
            esm_spec: null,
          },
        },
      ],
    }),
    /no complete open notification/u,
  );
  await assert.rejects(
    lifecycle.replace({
      files: {},
      modelNotifications: [
        openNotification(
          id,
          {},
          {
            url: "data:text/javascript,export const value = 1",
            hash: "invalid-module",
          },
        ),
      ],
    }),
    /missing a default export/u,
  );
  assert.equal(WIDGET_REGISTRY.getModelSync(id), undefined);
});

test("native model disposal restores prior page resources", async () => {
  browser.__MARIMO_STATIC__ = { files: { "existing.css": "data:text/css,body{}" } };
  lifecycle = createPreparedModelLifecycle();
  await (
    await lifecycle.replace({
      files: { "next.css": "data:text/css,main{}" },
      modelNotifications: [],
    })
  ).commit();
  assert.deepEqual(browser.__MARIMO_STATIC__?.files, { "next.css": "data:text/css,main{}" });

  await lifecycle.dispose();

  assert.deepEqual(browser.__MARIMO_STATIC__?.files, { "existing.css": "data:text/css,body{}" });
});

test("model disposal failures still release the page owner", async () => {
  lifecycle = createPreparedModelLifecycle();
  const id = modelId("prepared-disposal-failure");
  await (
    await lifecycle.replace({
      files: {},
      modelNotifications: [openNotification(id, { value: 7 })],
    })
  ).commit();
  const close = vi
    .spyOn(WIDGET_REGISTRY, "delete")
    .mockRejectedValueOnce(new Error("model close failed"));
  try {
    await assert.rejects(lifecycle.dispose(), /model close failed/u);
    lifecycle = undefined;
  } finally {
    close.mockRestore();
    await WIDGET_REGISTRY.delete(id);
  }
  lifecycle = createPreparedModelLifecycle();
  lifecycle.activate();
});
