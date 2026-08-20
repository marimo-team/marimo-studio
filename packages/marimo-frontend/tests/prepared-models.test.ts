// @vitest-environment jsdom

import type {
  ModelState,
  WidgetModelId,
} from "@marimo-team/frontend/unstable_internal/plugins/impl/anywidget/types";

import { WIDGET_REGISTRY } from "@marimo-team/frontend/unstable_internal/plugins/impl/anywidget/registry";
import assert from "node:assert/strict";
import { afterEach, test, vi } from "vite-plus/test";

import type {
  PreparedModelGraph,
  PreparedModelGraphFactory,
  PreparedModelGraphPort,
  PreparedModelGraphSnapshot,
  PreparedModelLifecycleNotification,
} from "../src/prepared-models.ts";

import {
  createPreparedModelLifecycle,
  PreparedModelGraphCheckpoint,
} from "../src/prepared-models.ts";

// SAFETY: The test observes the browser global owned by the prepared model facade.
const browser = globalThis as typeof globalThis & {
  __MARIMO_STATIC__?: { readonly files: Readonly<Record<string, string>> };
};

interface GraphHarness {
  readonly factory: PreparedModelGraphFactory;
  readonly checkpoint: PreparedModelGraphCheckpoint;
  readonly replace: ReturnType<typeof vi.fn<PreparedModelGraph["replace"]>>;
  readonly dispose: ReturnType<typeof vi.fn<PreparedModelGraph["dispose"]>>;
  port?: PreparedModelGraphPort;
  initial?: PreparedModelGraphSnapshot;
}

let dispose: (() => Promise<void>) | undefined;

const modelId = (value: string): WidgetModelId => {
  assert.ok(value.length > 0);
  // SAFETY: The assertion above matches Marimo's WidgetModelId predicate.
  return value as WidgetModelId;
};

const replacement = (adopted: PreparedModelGraphSnapshot | undefined) =>
  Object.freeze({
    mutated: true,
    remount: false,
    commit: async () => adopted,
    rollback: async () => {},
  });

const graphHarness = (): GraphHarness => {
  const checkpoint = new PreparedModelGraphCheckpoint();
  const replace = vi.fn<PreparedModelGraph["replace"]>(async (target) =>
    replacement(target instanceof PreparedModelGraphCheckpoint ? undefined : target),
  );
  const disposeGraph = vi.fn<PreparedModelGraph["dispose"]>(async () => {});
  const harness: GraphHarness = {
    checkpoint,
    replace,
    dispose: disposeGraph,
    factory(port, initial) {
      harness.port = port;
      harness.initial = initial;
      return {
        checkpoint: () => checkpoint,
        replace,
        dispose: disposeGraph,
      };
    },
  };
  return harness;
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

const graphTarget = (harness: GraphHarness, index: number): PreparedModelGraphSnapshot => {
  const target = harness.replace.mock.calls[index]?.[0];
  assert.ok(target);
  // SAFETY: These calls pass resources, so the facade sends a graph snapshot rather than a token.
  return target as PreparedModelGraphSnapshot;
};

afterEach(async () => {
  await dispose?.();
  dispose = undefined;
  vi.restoreAllMocks();
  delete browser.__MARIMO_STATIC__;
});

test("the facade delegates graph transactions through the injected capability", async () => {
  const harness = graphHarness();
  const lifecycle = createPreparedModelLifecycle(harness.factory);
  dispose = lifecycle.dispose;
  assert.deepEqual(harness.initial?.files, {});
  assert.equal(harness.initial?.records.size, 0);

  const resources = {
    files: { "widget.js": "data:text/javascript,export default {}" },
    modelNotifications: [openNotification(modelId("prepared-model"), { value: 7 })],
  };
  const staged = await lifecycle.replace(resources);
  await staged.commit();

  assert.equal(harness.replace.mock.calls.length, 1);
  const target = graphTarget(harness, 0);
  assert.deepEqual(target.files, resources.files);
  const record = target.records.get("prepared-model");
  assert.ok(record);
  assert.equal(record.active, true);
  assert.equal(record.notifications.length, 1);
});

test("the graph port replays, captures, restores, and closes native Marimo models", async () => {
  const harness = graphHarness();
  const lifecycle = createPreparedModelLifecycle(harness.factory);
  dispose = lifecycle.dispose;
  const id = modelId("prepared-native-model");
  await lifecycle.replace({
    files: {},
    modelNotifications: [openNotification(id, { value: 7 })],
  });
  const target = graphTarget(harness, 0);
  const record = target.records.get(id);
  assert.ok(record);
  const port = harness.port;
  assert.ok(port);

  await port.validate(record);
  await port.replay(record);
  const model = WIDGET_REGISTRY.getModelSync(id);
  assert.ok(model);
  model.set("value", 8);
  const captured = port.capture(id);
  model.set("value", 9);
  port.restore(id, captured);
  assert.equal(model.get("value"), 8);

  const merged = port.merge(record, captured);
  assert.notEqual(merged.canonical, record.canonical);
  await port.close(id);
  assert.equal(WIDGET_REGISTRY.getModelSync(id), undefined);
});

test("the graph port rejects malformed lifecycle and widget modules before replay", async () => {
  const harness = graphHarness();
  const lifecycle = createPreparedModelLifecycle(harness.factory);
  dispose = lifecycle.dispose;
  const id = modelId("prepared-invalid-model");
  await lifecycle.replace({
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
  });
  let target = graphTarget(harness, 0);
  let record = target.records.get(id);
  assert.ok(record);
  const port = harness.port;
  assert.ok(port);
  await assert.rejects(port.validate(record), /no complete open notification/u);

  await lifecycle.replace({
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
  });
  target = graphTarget(harness, 1);
  record = target.records.get(id);
  assert.ok(record);
  await assert.rejects(port.preflight(record), /missing a default export/u);
});

test("model checkpoints stay opaque while resources remain presentation-owned", async () => {
  const harness = graphHarness();
  const lifecycle = createPreparedModelLifecycle(harness.factory);
  dispose = lifecycle.dispose;
  const checkpointResources = lifecycle.snapshot();

  assert.deepEqual(checkpointResources, { files: {}, modelNotifications: [] });
  await lifecycle.replace(checkpointResources);

  assert.equal(harness.replace.mock.calls[0]?.[0], harness.checkpoint);
});

test("static files remain in the Marimo adapter and prior page state is restored", async () => {
  browser.__MARIMO_STATIC__ = { files: { "existing.css": "data:text/css,body{}" } };
  const harness = graphHarness();
  const lifecycle = createPreparedModelLifecycle(harness.factory);
  dispose = lifecycle.dispose;
  const port = harness.port;
  assert.ok(port);

  port.setFiles({ "next.css": "data:text/css,main{}" });
  assert.deepEqual(browser.__MARIMO_STATIC__?.files, {
    "next.css": "data:text/css,main{}",
  });
  lifecycle.activate();
  await lifecycle.dispose();
  dispose = undefined;

  assert.deepEqual(browser.__MARIMO_STATIC__?.files, {
    "existing.css": "data:text/css,body{}",
  });
  assert.equal(harness.dispose.mock.calls.length, 1);
});

test("graph disposal failures still release the page owner", async () => {
  const harness = graphHarness();
  harness.dispose.mockRejectedValueOnce(new Error("graph disposal failed"));
  const lifecycle = createPreparedModelLifecycle(harness.factory);
  lifecycle.activate();

  await assert.rejects(lifecycle.dispose(), /graph disposal failed/u);

  const retry = createPreparedModelLifecycle(graphHarness().factory);
  dispose = retry.dispose;
  retry.activate();
});
