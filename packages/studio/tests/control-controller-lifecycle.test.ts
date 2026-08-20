import type { RuntimeControls } from "@marimo-studio/protocol/runtime-config";

import { afterEach, expect, it, vi } from "vite-plus/test";

import type { fetchRuntimeControls } from "../src/features/preview/control-remote.ts";
import type { ControlEndpoint } from "../src/features/preview/control-types.ts";

import { RuntimeControlRequestError } from "../src/features/preview/control-remote.ts";
import { changed, createControlController, endpoint } from "./control-controller-fixture.ts";

afterEach(() => {
  vi.useRealTimers();
});

it("unwinds a partial binding subscription before retrying setup", async () => {
  vi.useFakeTimers();
  const controls: RuntimeControls = { bindings: {} };
  const stopEditorSubscription = vi.fn();
  const firstEditor = {
    ...endpoint(controls),
    subscribeControlBindings: vi.fn(() => stopEditorSubscription),
  } satisfies ControlEndpoint;
  const firstPreview = {
    ...endpoint(controls),
    subscribeControlBindings: vi.fn(() => {
      throw new Error("preview subscription failed");
    }),
  } satisfies ControlEndpoint;
  const nextEditor = endpoint(controls);
  const nextPreview = endpoint(controls);
  const connect = vi
    .fn()
    .mockReturnValueOnce(firstEditor)
    .mockReturnValueOnce(firstPreview)
    .mockReturnValueOnce(nextEditor)
    .mockReturnValueOnce(nextPreview);
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(async (_support, runtime) =>
    changed({ schema: 1, revision: "revision-1", runtime, controls }),
  );
  const { controller } = createControlController({ connect, fetchControls });

  controller.begin("revision-1", "s_123456");
  await vi.waitFor(() => expect(firstPreview.subscribeControlBindings).toHaveBeenCalledOnce());

  expect(stopEditorSubscription).toHaveBeenCalledOnce();
  expect(firstEditor.dispose).toHaveBeenCalledOnce();
  expect(firstPreview.dispose).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(100);
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(4));
  controller.stop();
});

it("attempts every control cleanup after a disposer rejects", async () => {
  const controls: RuntimeControls = { bindings: {} };
  const subscriptionStops = [
    vi.fn(() => {
      throw new Error("editor subscription cleanup failed");
    }),
    vi.fn(() => {
      throw new Error("preview subscription cleanup failed");
    }),
  ];
  const endpoints = subscriptionStops.map((stop) => {
    const current = endpoint(controls);
    return {
      ...current,
      subscribeControlBindings: vi.fn(() => stop),
      dispose: vi.fn(() => {
        throw new Error("endpoint cleanup failed");
      }),
    } satisfies ControlEndpoint;
  });
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(async (_support, runtime) =>
    changed({ schema: 1, revision: "revision-1", runtime, controls }),
  );
  const connect = vi.fn().mockReturnValueOnce(endpoints[0]).mockReturnValueOnce(endpoints[1]);
  const { controller } = createControlController({ connect, fetchControls });

  controller.begin("revision-1", "s_123456");
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));

  expect(() => controller.stop()).toThrow(AggregateError);
  expect(subscriptionStops[0]).toHaveBeenCalledOnce();
  expect(subscriptionStops[1]).toHaveBeenCalledOnce();
  expect(endpoints[0]?.dispose).toHaveBeenCalledOnce();
  expect(endpoints[1]?.dispose).toHaveBeenCalledOnce();
  expect(() => controller.stop()).not.toThrow();
});

it("stops polling and requests a reload when the revision is unavailable", async () => {
  vi.useFakeTimers();
  let editorReads = 0;
  let previewReads = 0;
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(async (_support, runtime, ...rest) => {
    if (runtime === "editor") {
      editorReads += 1;
      if (editorReads > 1) {
        throw new RuntimeControlRequestError(
          "presentation-revision-unavailable",
          409,
          true,
          "Presentation revision unavailable",
        );
      }
    } else {
      previewReads += 1;
      if (previewReads > 1) {
        return { kind: "unchanged", etag: rest[3] ?? '"preview-1"' };
      }
    }
    return changed({
      schema: 1,
      revision: "revision-1",
      runtime,
      controls: { native: { cells: {} } },
    });
  });
  const onContextUnavailable = vi.fn();
  const connect = vi.fn(() => endpoint());
  const { controller } = createControlController({
    connect,
    fetchControls,
    onContextUnavailable,
  });

  controller.begin("revision-1", "s_123456");
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));
  await vi.advanceTimersByTimeAsync(1_000);
  await vi.waitFor(() => expect(onContextUnavailable).toHaveBeenCalledOnce());
  const readsAfterReload = { editorReads, previewReads };
  await vi.runAllTimersAsync();

  expect({ editorReads, previewReads }).toEqual(readsAfterReload);
  expect(onContextUnavailable).toHaveBeenCalledOnce();
});

it("retries a pending session before reloading with a fresh binding", async () => {
  vi.useFakeTimers();
  let editorReads = 0;
  let previewReads = 0;
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(async (_support, runtime, ...rest) => {
    if (runtime === "editor") {
      editorReads += 1;
      if (editorReads > 1) {
        throw new RuntimeControlRequestError(
          "runtime-sync-pending",
          409,
          true,
          "Editor session pending",
        );
      }
    } else {
      previewReads += 1;
      if (previewReads > 1) {
        return { kind: "unchanged", etag: rest[3] ?? '"preview-1"' };
      }
    }
    return changed({
      schema: 1,
      revision: "revision-1",
      runtime,
      controls: { native: { cells: {} } },
    });
  });
  const onContextUnavailable = vi.fn();
  const connect = vi.fn(() => endpoint());
  const { controller } = createControlController({
    connect,
    fetchControls,
    onContextUnavailable,
  });

  controller.begin("revision-1", "s_123456");
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));
  await vi.advanceTimersByTimeAsync(2_000);
  expect(onContextUnavailable).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1_000);
  await vi.waitFor(() => expect(onContextUnavailable).toHaveBeenCalledOnce());
  const readsAfterReload = { editorReads, previewReads };
  await vi.runAllTimersAsync();

  expect({ editorReads, previewReads }).toEqual(readsAfterReload);
  expect(editorReads).toBe(4);
  expect(onContextUnavailable).toHaveBeenCalledOnce();
});
