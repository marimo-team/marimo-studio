import type {
  RuntimeControlBinding,
  RuntimeControls,
} from "@marimo-studio/protocol/runtime-config";

import { afterEach, expect, it, vi } from "vite-plus/test";

import type { fetchRuntimeControls } from "../src/features/preview/control-remote.ts";
import type { ControlEndpoint } from "../src/features/preview/control-types.ts";

import {
  changed,
  createControlController,
  endpoint,
  TopologyEndpoint,
} from "./control-controller-fixture.ts";

afterEach(() => {
  vi.useRealTimers();
});

it("refreshes controls when a prepared publication adds bindings", async () => {
  vi.useFakeTimers();
  const region: RuntimeControlBinding = {
    input: "filters",
    path: [{ kind: "key", value: "region" }],
  };
  const detail: RuntimeControlBinding = {
    input: "filters",
    path: [{ kind: "key", value: "detail" }],
  };
  const initial = { "prepared-region": region };
  const grown = { ...initial, "prepared-detail": detail };
  let editorRequest = 0;
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(async (_support, runtime) => {
    if (runtime === "editor") {
      editorRequest += 1;
      const controls: RuntimeControls = {
        bindings:
          editorRequest === 1
            ? { "editor-region": region }
            : { "editor-region": region, "editor-detail": detail },
      };
      return changed({ schema: 1, revision: "revision-1", runtime, controls });
    }
    return changed({ schema: 1, revision: "revision-1", runtime });
  });
  let grownPublished = false;
  let publishBindings = (_bindings: NonNullable<RuntimeControls["bindings"]>) => {};
  const initialPreview: ControlEndpoint = {
    ...endpoint({ bindings: initial }),
    controlBindings: () => (grownPublished ? grown : initial),
    subscribeControlBindings(listener) {
      publishBindings = (bindings) => {
        grownPublished = true;
        listener(bindings);
      };
      return () => {};
    },
  };
  const connect = vi.fn().mockReturnValueOnce(endpoint()).mockReturnValueOnce(initialPreview);
  const { controller } = createControlController({ connect, fetchControls });

  controller.begin("revision-1", "s_123456");
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));
  publishBindings(grown);
  await vi.advanceTimersByTimeAsync(1_000);
  await vi.waitFor(() => expect(fetchControls).toHaveBeenCalledTimes(4));

  expect(connect).toHaveBeenCalledTimes(2);
  expect(fetchControls).toHaveBeenCalledTimes(4);
  controller.stop();
});

it("refreshes controls when an editor rerun replaces an object ID", async () => {
  vi.useFakeTimers();
  const binding: RuntimeControlBinding = {
    input: "filters",
    path: [{ kind: "key", value: "region" }],
  };
  const oldEditorBindings = { "editor-old-region": binding };
  const newEditorBindings = { "editor-new-region": binding };
  const previewBindings = { "prepared-region": binding };
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(
    async (_support, runtime, _session, _revision, _client, etag) => {
      if (runtime === "editor") {
        if (etag === undefined) {
          return changed({
            schema: 1,
            revision: "revision-1",
            runtime,
            controls: { bindings: oldEditorBindings },
          });
        }
        if (etag === '"etag-1"') {
          return changed(
            {
              schema: 1,
              revision: "revision-1",
              runtime,
              controls: { bindings: oldEditorBindings },
            },
            2,
          );
        }
        if (etag === '"etag-2"') {
          return changed(
            {
              schema: 1,
              revision: "revision-1",
              runtime,
              controls: { bindings: newEditorBindings },
            },
            3,
          );
        }
        return { kind: "unchanged", etag: '"etag-3"' };
      }
      return etag === undefined
        ? changed({ schema: 1, revision: "revision-1", runtime })
        : { kind: "unchanged", etag };
    },
  );
  const connect = vi
    .fn()
    .mockReturnValueOnce(endpoint({ bindings: oldEditorBindings }))
    .mockReturnValueOnce(endpoint({ bindings: previewBindings }));
  const { controller } = createControlController({ connect, fetchControls });

  controller.begin("revision-1", "s_123456");
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));
  await vi.advanceTimersByTimeAsync(1_000);
  await Promise.resolve();
  expect(connect).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(1_000);
  await vi.waitFor(() => expect(fetchControls).toHaveBeenCalledTimes(6));

  expect(connect).toHaveBeenCalledTimes(2);
  expect(fetchControls).toHaveBeenCalledTimes(6);
  expect(fetchControls.mock.calls[2]?.[5]).toBe('"etag-1"');
  controller.stop();
  await vi.advanceTimersByTimeAsync(5_000);
  expect(fetchControls).toHaveBeenCalledTimes(6);
});

it("replays editor input emitted before its new binding is published", async () => {
  const binding: RuntimeControlBinding = { input: "filters", path: [] };
  const oldBindings = { "editor-old": binding };
  const newBindings = { "editor-new": binding };
  const previewBindings = { "prepared-filter": binding };
  const editor = new TopologyEndpoint(oldBindings, new Map());
  const previewEndpoint = new TopologyEndpoint(
    previewBindings,
    new Map([["prepared-filter", null]]),
  );
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(async (_support, runtime) =>
    changed({
      schema: 1,
      revision: "revision-1",
      runtime,
      controls: { bindings: runtime === "editor" ? oldBindings : previewBindings },
    }),
  );
  const connect = vi.fn().mockReturnValueOnce(editor).mockReturnValueOnce(previewEndpoint);
  const { controller } = createControlController({ connect, fetchControls });
  controller.begin("revision-1", "s_123456");
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));

  editor.emit({ objectId: "editor-new", value: { region: ["Europe"] } });
  expect(previewEndpoint.applied).toEqual([]);
  editor.publishBindings(newBindings);
  await vi.waitFor(() => expect(previewEndpoint.applied).toHaveLength(1));

  expect(previewEndpoint.applied).toEqual([
    [{ objectId: "prepared-filter", value: { region: ["Europe"] } }],
  ]);
  controller.stop();
});

it("quarantines a reused editor ID while refreshed bindings are pending", async () => {
  vi.useFakeTimers();
  const scale: RuntimeControlBinding = { input: "scale", path: [] };
  const root: RuntimeControlBinding = { input: "filters", path: [] };
  const region: RuntimeControlBinding = {
    input: "filters",
    path: [{ kind: "element" }, { kind: "key", value: "region" }],
  };
  const detail: RuntimeControlBinding = {
    input: "filters",
    path: [{ kind: "element" }, { kind: "key", value: "detail" }],
  };
  const oldBindings = { "live-scale": scale, "live-reused": root };
  const currentBindings = {
    "live-scale": scale,
    "live-root": root,
    "live-reused": region,
    "live-detail": detail,
  };
  const previewBindings = {
    "prepared-scale": scale,
    "prepared-a-root": root,
    "prepared-b-root": root,
  };
  const oldEditor = new TopologyEndpoint(
    oldBindings,
    new Map<string, unknown>([
      ["live-scale", 3],
      ["live-reused", null],
    ]),
    false,
  );
  const oldPreview = new TopologyEndpoint(
    previewBindings,
    new Map<string, unknown>([
      ["prepared-scale", 3],
      ["prepared-a-root", null],
      ["prepared-b-root", null],
      ["prepared-a-detail", "ready"],
      ["prepared-b-detail", "ready"],
    ]),
  );
  let editorRead = 0;
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(async (_support, runtime) => {
    if (runtime !== "editor") {
      return changed({ schema: 1, revision: "revision-1", runtime });
    }
    editorRead += 1;
    if (editorRead === 1) {
      return changed({
        schema: 1,
        revision: "revision-1",
        runtime,
        controls: { bindings: oldBindings },
      });
    }
    return changed(
      {
        schema: 1,
        revision: "revision-1",
        runtime,
        controls: { bindings: currentBindings },
      },
      2,
    );
  });
  const connect = vi.fn().mockReturnValueOnce(oldEditor).mockReturnValueOnce(oldPreview);
  const { controller } = createControlController({ connect, fetchControls });

  controller.begin("revision-1", "s_123456");
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));
  await vi.advanceTimersByTimeAsync(1);
  expect(oldEditor.subscriberCount()).toBe(1);
  oldPreview.emit({ objectId: "prepared-scale", value: 1 });
  await vi.waitFor(() => expect(oldEditor.applied).toHaveLength(1));
  Object.assign(previewBindings, {
    "prepared-a-detail": detail,
    "prepared-b-detail": detail,
  });
  oldEditor.register({ objectId: "live-dictionary", value: { region: ["Europe"] } });
  oldPreview.emit({ objectId: "prepared-scale", value: 3 });
  oldEditor.emit({ objectId: "live-reused", value: ["Europe"] });
  oldEditor.emit({ objectId: "live-detail", value: "from editor" });
  oldEditor.emit({ objectId: "live-scale", value: 1 });

  expect(oldPreview.applied).toEqual([]);
  await vi.advanceTimersByTimeAsync(1_000);
  await vi.waitFor(() => expect(oldPreview.applied).toHaveLength(2));

  expect(connect).toHaveBeenCalledTimes(2);
  expect(oldEditor.applied).toEqual([
    [{ objectId: "live-scale", value: 1 }],
    [{ objectId: "live-scale", value: 3 }],
  ]);
  expect(oldPreview.applied).toEqual([
    [
      { objectId: "prepared-a-detail", value: "from editor" },
      { objectId: "prepared-b-detail", value: "from editor" },
    ],
    [{ objectId: "prepared-scale", value: 1 }],
  ]);
  controller.stop();
});

it("forces one controls snapshot after a stable native re-registration", async () => {
  vi.useFakeTimers();
  const binding: RuntimeControlBinding = { input: "scale", path: [] };
  const editorBindings = { "live-scale": binding };
  const previewBindings = { "prepared-scale": binding };
  const editor = new TopologyEndpoint(editorBindings, new Map([["live-scale", 3]]), false);
  const previewEndpoint = new TopologyEndpoint(previewBindings, new Map([["prepared-scale", 3]]));
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(
    async (_support, runtime, _session, _revision, _client, etag) => {
      if (runtime === "editor") {
        return changed({
          schema: 1,
          revision: "revision-1",
          runtime,
          controls: { bindings: editorBindings },
        });
      }
      return etag === undefined
        ? changed({ schema: 1, revision: "revision-1", runtime })
        : { kind: "unchanged", etag };
    },
  );
  const connect = vi.fn().mockReturnValueOnce(editor).mockReturnValueOnce(previewEndpoint);
  const { controller } = createControlController({ connect, fetchControls });

  controller.begin("revision-1", "s_123456");
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));
  await vi.advanceTimersByTimeAsync(1);
  expect(editor.subscriberCount()).toBe(1);
  editor.register({ objectId: "live-scale", value: 3 });
  editor.emit({ objectId: "live-scale", value: 1 });
  await vi.advanceTimersByTimeAsync(1_000);
  await vi.waitFor(() => expect(previewEndpoint.applied).toHaveLength(1));

  const editorReads = fetchControls.mock.calls.filter((call) => call[1] === "editor");
  expect(editorReads).toHaveLength(2);
  expect(editorReads[1]?.[5]).toBeUndefined();
  expect(previewEndpoint.applied).toEqual([[{ objectId: "prepared-scale", value: 1 }]]);
  expect(connect).toHaveBeenCalledTimes(2);
  controller.stop();
});
