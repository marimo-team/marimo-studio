import { parseFrameBridgeMessage } from "@marimo-studio/protocol/frame-bridge";
import { afterEach, expect, it, vi } from "vite-plus/test";

import type { EditorQuerySyncResult } from "../src/features/preview/query-remote.ts";

import { PreviewQueryController } from "../src/features/preview/query-controller.ts";
import { createFrameBridgeSource, installFrameBridge } from "./frame-bridge-test-support.ts";

type SyncEditorQuery = ConstructorParameters<typeof PreviewQueryController>[3];

afterEach(() => {
  vi.useRealTimers();
  document.body.replaceChildren();
});

const deferred = () => {
  let resolve!: (result: EditorQuerySyncResult) => void;
  let reject!: (cause: Error) => void;
  const promise = new Promise<EditorQuerySyncResult>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, reject, resolve };
};

const frame = () => document.createElement("iframe");

it("applies an editor query through the rendered preview bridge", async () => {
  const preview = frame();
  const source = createFrameBridgeSource();
  installFrameBridge(preview, source, {
    lifecycleId: 1,
    revision: "revision-1",
    runtime: "wasm",
    sessionId: null,
    view: "dashboard",
  });
  const controller = new PreviewQueryController("wasm", preview, vi.fn(), vi.fn(), vi.fn());

  controller.editorChanged("region=emea", true);

  await vi.waitFor(() =>
    expect(source.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "marimo-studio:frame-query-apply",
        query: "?region=emea",
      }),
      "*",
    ),
  );
  controller.cancel();
  preview.remove();
});

it("reports WebAssembly query failure until the preview retry succeeds", async () => {
  vi.useFakeTimers();
  const preview = frame();
  let attempt = 0;
  const source = createFrameBridgeSource((message) => {
    if (message.type === "marimo-studio:frame-query-apply" && attempt++ === 0) {
      return "worker unavailable";
    }
  });
  installFrameBridge(preview, source, {
    lifecycleId: 1,
    revision: "revision-1",
    runtime: "wasm",
    sessionId: null,
    view: "dashboard",
  });
  const statuses: string[] = [];
  const controller = new PreviewQueryController(
    "wasm",
    preview,
    vi.fn(),
    vi.fn(),
    vi.fn(),
    "",
    (status) => statuses.push(status.phase),
  );
  vi.spyOn(console, "warn").mockImplementation(() => undefined);

  controller.editorChanged("region=emea", true);
  await vi.waitFor(() => expect(statuses).toContain("degraded"));
  await vi.advanceTimersByTimeAsync(1_000);
  await vi.waitFor(() => expect(statuses.at(-1)).toBe("ready"));

  expect(
    source.postMessage.mock.calls.filter(
      ([message]) => parseFrameBridgeMessage(message)?.type === "marimo-studio:frame-query-apply",
    ),
  ).toHaveLength(2);
  controller.cancel();
  preview.remove();
});

it("serializes writes and coalesces them to the latest query", async () => {
  const first = deferred();
  const second = deferred();
  const sync = vi
    .fn<SyncEditorQuery>()
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise);
  const controller = new PreviewQueryController("wasm", frame(), vi.fn(), sync, vi.fn());

  controller.previewChanged("region=emea");
  controller.previewChanged("region=apac");
  controller.previewChanged("region=americas");

  expect(sync).toHaveBeenCalledTimes(1);
  expect(sync.mock.calls[0]?.[0]).toBe("?region=emea");

  first.resolve("accepted");
  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(2));
  expect(sync.mock.calls[1]?.[0]).toBe("?region=americas");
  second.resolve("accepted");
  await second.promise;
  controller.cancel();
});

it("retries the latest query after the editor reconnects", async () => {
  vi.useFakeTimers();
  const sync = vi
    .fn<SyncEditorQuery>()
    .mockResolvedValueOnce("retry")
    .mockResolvedValueOnce("accepted");
  const controller = new PreviewQueryController("wasm", frame(), vi.fn(), sync, vi.fn());

  controller.previewChanged("region=emea");
  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(1));
  await vi.advanceTimersByTimeAsync(1_000);

  expect(sync).toHaveBeenCalledTimes(2);
  expect(sync.mock.calls.map(([query]) => query)).toEqual(["?region=emea", "?region=emea"]);
  expect(sync.mock.calls[1]?.[1]).toBe(sync.mock.calls[0]?.[1]);
  expect(sync.mock.calls[1]?.[2]).toBe(sync.mock.calls[0]?.[2]);
  controller.cancel();
});

it("reports a rejected editor write until its retry recovers", async () => {
  vi.useFakeTimers();
  const sync = vi
    .fn<SyncEditorQuery>()
    .mockRejectedValueOnce(new Error("editor write failed"))
    .mockResolvedValueOnce("accepted");
  const statuses: string[] = [];
  const controller = new PreviewQueryController(
    "wasm",
    frame(),
    vi.fn(),
    sync,
    vi.fn(),
    "",
    (status) => statuses.push(status.phase),
  );
  vi.spyOn(console, "warn").mockImplementation(() => undefined);

  controller.previewChanged("region=apac");
  await vi.waitFor(() => expect(statuses.at(-1)).toBe("degraded"));
  await vi.runOnlyPendingTimersAsync();
  await vi.waitFor(() => expect(statuses.at(-1)).toBe("ready"));

  expect(sync).toHaveBeenCalledTimes(2);
  controller.cancel();
});

it("accepts a server navigation query without committing parent query state", async () => {
  const operation = deferred();
  const sync = vi.fn<SyncEditorQuery>(() => operation.promise);
  const syncQuery = vi.fn();
  const controller = new PreviewQueryController("server", frame(), syncQuery, sync, vi.fn());

  const navigation = controller.synchronizeNavigation("region=apac");

  expect(sync).toHaveBeenCalledOnce();
  expect(sync.mock.calls[0]?.[0]).toBe("?region=apac");
  const operationId = sync.mock.calls[0]?.[1];
  expect(operationId).toMatch(/^query_/);
  operation.resolve("accepted");
  await operation.promise;
  controller.editorChanged("region=apac", false, operationId);
  controller.editorChanged("region=apac", false, operationId, true);
  await expect(navigation).resolves.toBe(true);
  controller.commitNavigation("region=apac");
  expect(syncQuery).not.toHaveBeenCalled();
  expect(sync).toHaveBeenCalledOnce();
  controller.cancel();
});

it("restores an accepted navigation query when staged view readiness fails", async () => {
  const sync = vi.fn<SyncEditorQuery>(async () => "accepted");
  const controller = new PreviewQueryController("server", frame(), vi.fn(), sync, vi.fn(), "");

  const navigation = controller.synchronizeNavigation("?region=apac");
  await vi.waitFor(() => expect(sync).toHaveBeenCalledOnce());
  const navigationOperation = sync.mock.calls[0]?.[1];
  controller.editorChanged("?region=apac", false, navigationOperation, true);
  await expect(navigation).resolves.toBe(true);

  const rollback = controller.rollbackNavigation();
  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(2));
  expect(sync.mock.calls.map(([query]) => query)).toEqual(["?region=apac", ""]);
  const rollbackOperation = sync.mock.calls[1]?.[1];
  controller.editorChanged("", false, rollbackOperation, true);
  await expect(rollback).resolves.toBe(true);
  expect(controller.currentQuery).toBe("");
  controller.cancel();
});

it("repairs an accepted navigation when its completion marker is lost", async () => {
  vi.useFakeTimers();
  const syncQuery = vi.fn();
  const sync = vi.fn<SyncEditorQuery>(async () => "accepted");
  const controller = new PreviewQueryController("server", frame(), syncQuery, sync, vi.fn());

  const navigation = controller.synchronizeNavigation("region=apac");
  let settled = false;
  void navigation.then(() => {
    settled = true;
  });
  await vi.advanceTimersByTimeAsync(0);

  expect(settled).toBe(false);
  await vi.advanceTimersByTimeAsync(10_000);
  await expect(navigation).resolves.toBe(false);
  expect(controller.currentQuery).toBe("");
  expect(sync).toHaveBeenCalledTimes(2);
  expect(sync.mock.calls[1]?.[0]).toBe("");
  expect(syncQuery).not.toHaveBeenCalled();
  controller.cancel();
});

it("ignores an old controller operation while accepting an untagged editor change", async () => {
  const oldSync = vi.fn<SyncEditorQuery>(async () => "accepted");
  const oldController = new PreviewQueryController(
    "wasm",
    frame(),
    vi.fn(),
    oldSync,
    vi.fn(),
    "?view=old",
  );
  oldController.previewChanged("view=staged");
  await vi.waitFor(() => expect(oldSync).toHaveBeenCalledOnce());
  const oldOperation = oldSync.mock.calls[0]?.[1];

  const syncQuery = vi.fn();
  const changed = vi.fn();
  const currentController = new PreviewQueryController(
    "server",
    frame(),
    syncQuery,
    vi.fn(),
    changed,
    "?view=current",
  );
  currentController.editorChanged("?view=staged", false, oldOperation, true);

  expect(currentController.currentQuery).toBe("?view=current");
  expect(syncQuery).not.toHaveBeenCalled();
  expect(changed).not.toHaveBeenCalled();

  currentController.editorChanged("?view=external", false);

  expect(currentController.currentQuery).toBe("?view=external");
  expect(syncQuery).toHaveBeenCalledWith("?view=external");
  expect(changed).toHaveBeenCalledOnce();
  oldController.cancel();
  currentController.cancel();
});

it("ignores a late completion after its operation history is evicted", async () => {
  const syncQuery = vi.fn();
  const changed = vi.fn();
  const sync = vi.fn<SyncEditorQuery>(async () => "accepted");
  const controller = new PreviewQueryController("wasm", frame(), syncQuery, sync, changed);

  controller.previewChanged("entry=0");
  await vi.waitFor(() => expect(sync).toHaveBeenCalledOnce());
  const retiredOperation = sync.mock.calls[0]?.[1];

  // Cross the bounded operation history so the first accepted write is no
  // longer retained when its delayed completion arrives.
  for (let entry = 1; entry <= 100; entry += 1) {
    controller.previewChanged(`entry=${entry}`);
    await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(entry + 1));
  }
  const changeCount = changed.mock.calls.length;
  const queryCount = syncQuery.mock.calls.length;

  controller.editorChanged("entry=0", false, retiredOperation, true);

  expect(controller.currentQuery).toBe("?entry=100");
  expect(changed).toHaveBeenCalledTimes(changeCount);
  expect(syncQuery).toHaveBeenCalledTimes(queryCount);
  controller.cancel();
});

it("keeps write generations monotonic across controller recreation", async () => {
  const firstSync = vi.fn<SyncEditorQuery>(async () => "accepted");
  const first = new PreviewQueryController("wasm", frame(), vi.fn(), firstSync, vi.fn(), "");
  first.previewChanged("view=first");
  await vi.waitFor(() => expect(firstSync).toHaveBeenCalledOnce());
  const firstGeneration = firstSync.mock.calls[0]?.[2];
  if (firstGeneration === undefined) {
    throw new Error("The first query write was not assigned a generation.");
  }
  first.cancel();

  const secondSync = vi.fn<SyncEditorQuery>(async () => "accepted");
  const second = new PreviewQueryController("wasm", frame(), vi.fn(), secondSync, vi.fn(), "");
  second.previewChanged("view=second");
  await vi.waitFor(() => expect(secondSync).toHaveBeenCalledOnce());

  expect(secondSync.mock.calls[0]?.[2]).toBeGreaterThan(firstGeneration);
  second.cancel();
});

it("does not treat local query equality as committed editor state", async () => {
  const first = deferred();
  const second = deferred();
  const sync = vi
    .fn<SyncEditorQuery>()
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise);
  const controller = new PreviewQueryController("wasm", frame(), vi.fn(), sync, vi.fn());

  controller.previewChanged("region=apac");
  const navigation = controller.synchronizeNavigation("region=apac");
  let settled = false;
  void navigation.then(() => {
    settled = true;
  });
  await Promise.resolve();

  expect(settled).toBe(false);
  first.resolve("retry");
  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(2));
  second.resolve("accepted");
  const operationId = sync.mock.calls[1]?.[1];
  controller.editorChanged("region=apac", false, operationId, true);
  await expect(navigation).resolves.toBe(true);
  controller.cancel();
});

it("restores the committed query when a dispatched navigation echoes after cancellation", async () => {
  const dispatched = deferred();
  const sync = vi
    .fn<SyncEditorQuery>()
    .mockReturnValueOnce(dispatched.promise)
    .mockResolvedValue("accepted");
  const controller = new PreviewQueryController(
    "server",
    frame(),
    vi.fn(),
    sync,
    vi.fn(),
    "?region=emea",
  );

  const navigation = controller.synchronizeNavigation("?region=apac");
  const operationId = sync.mock.calls[0]?.[1];
  controller.cancelNavigation();
  await expect(navigation).resolves.toBe(false);
  controller.editorChanged("?region=apac", false, operationId, true);
  expect(sync).toHaveBeenCalledOnce();
  dispatched.resolve("accepted");
  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(2));

  expect(sync.mock.calls[1]?.[0]).toBe("?region=emea");
  expect(controller.currentQuery).toBe("?region=emea");
  controller.cancel();
});

it("does not compensate a dispatched operation proven unqueued", async () => {
  const dispatched = deferred();
  const sync = vi.fn<SyncEditorQuery>(() => dispatched.promise);
  const controller = new PreviewQueryController(
    "server",
    frame(),
    vi.fn(),
    sync,
    vi.fn(),
    "?region=emea",
  );

  const navigation = controller.synchronizeNavigation("?region=apac");
  const operationId = sync.mock.calls[0]?.[1];
  controller.cancelNavigation();
  await expect(navigation).resolves.toBe(false);
  dispatched.resolve("retry");
  await dispatched.promise;
  controller.editorChanged("?region=apac", false, operationId, true);

  expect(sync).toHaveBeenCalledOnce();
  expect(controller.currentQuery).toBe("?region=emea");
  controller.cancel();
});

it("queues a superseded echo until the newer navigation commits", async () => {
  const dispatched = deferred();
  const sync = vi
    .fn<SyncEditorQuery>()
    .mockReturnValueOnce(dispatched.promise)
    .mockResolvedValue("accepted");
  const controller = new PreviewQueryController(
    "server",
    frame(),
    vi.fn(),
    sync,
    vi.fn(),
    "?region=emea",
  );

  const firstNavigation = controller.synchronizeNavigation("?region=apac");
  const firstOperation = sync.mock.calls[0]?.[1];
  const newerNavigation = controller.synchronizeNavigation("?region=americas");
  await expect(firstNavigation).resolves.toBe(false);
  dispatched.resolve("accepted");
  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(2));
  const newerOperation = sync.mock.calls[1]?.[1];
  expect(sync.mock.calls[1]?.[0]).toBe("?region=americas");
  controller.editorChanged("?region=apac", false, firstOperation, true);
  expect(sync).toHaveBeenCalledTimes(2);
  controller.editorChanged("?region=americas", false, newerOperation, true);
  await expect(newerNavigation).resolves.toBe(true);
  expect(sync).toHaveBeenCalledTimes(2);
  controller.commitNavigation("?region=americas");

  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(3));
  expect(sync.mock.calls[2]?.[0]).toBe("?region=americas");
  expect(controller.currentQuery).toBe("?region=americas");
  controller.cancel();
});

it("restores the prior commit when a newer navigation fails after an old echo", async () => {
  const first = deferred();
  const second = deferred();
  const sync = vi
    .fn<SyncEditorQuery>()
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise)
    .mockResolvedValue("accepted");
  const controller = new PreviewQueryController(
    "server",
    frame(),
    vi.fn(),
    sync,
    vi.fn(),
    "?region=emea",
  );
  vi.spyOn(console, "warn").mockImplementation(() => undefined);

  const firstNavigation = controller.synchronizeNavigation("?region=apac");
  const firstOperation = sync.mock.calls[0]?.[1];
  const newerNavigation = controller.synchronizeNavigation("?region=americas");
  await expect(firstNavigation).resolves.toBe(false);
  first.resolve("accepted");
  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(2));
  controller.editorChanged("?region=apac", false, firstOperation, true);
  expect(sync).toHaveBeenCalledTimes(2);

  second.reject(new Error("query rejected"));
  await expect(newerNavigation).resolves.toBe(false);
  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(3));
  expect(sync.mock.calls[2]?.[0]).toBe("?region=emea");
  expect(controller.currentQuery).toBe("?region=emea");
  controller.cancel();
});

it("keeps the current query when a navigation write fails", async () => {
  const syncQuery = vi.fn();
  const sync = vi.fn<SyncEditorQuery>(async () => {
    throw new Error("query write failed");
  });
  const controller = new PreviewQueryController("server", frame(), syncQuery, sync, vi.fn());
  vi.spyOn(console, "warn").mockImplementation(() => undefined);

  await expect(controller.synchronizeNavigation("region=apac")).resolves.toBe(false);

  expect(syncQuery).not.toHaveBeenCalled();
  expect(sync.mock.calls.map(([query]) => query)).toEqual(["?region=apac", ""]);
  controller.cancel();
});

it("preserves newer editor intent across a delayed preview echo", async () => {
  const first = deferred();
  const sync = vi
    .fn<SyncEditorQuery>()
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce("accepted");
  const controller = new PreviewQueryController("wasm", frame(), vi.fn(), sync, vi.fn());

  controller.previewChanged("region=preview");
  const operationId = sync.mock.calls[0]?.[1];
  expect(operationId).toBeTypeOf("string");
  controller.editorChanged("region=editor", false);
  controller.editorChanged("region=preview", false, operationId);
  controller.editorChanged("region=preview", false, operationId, true);
  first.resolve("accepted");

  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(2));
  expect(sync.mock.calls.map(([query]) => query)).toEqual(["?region=preview", "?region=editor"]);
  controller.cancel();
});

it("keeps a real editor change that equals an in-flight preview query", async () => {
  const first = deferred();
  const sync = vi
    .fn<SyncEditorQuery>()
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce("accepted");
  const changed = vi.fn();
  const controller = new PreviewQueryController("wasm", frame(), vi.fn(), sync, changed);

  controller.previewChanged("region=preview");
  controller.editorChanged("region=editor", false);
  controller.editorChanged("region=preview", false);
  first.resolve("accepted");

  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(2));
  expect(sync.mock.calls.map(([query]) => query)).toEqual(["?region=preview", "?region=preview"]);
  expect(changed).toHaveBeenCalledTimes(3);
  controller.cancel();
});

it("preserves newer editor intent when an accepted response is lost", async () => {
  vi.useFakeTimers();
  const first = deferred();
  const sync = vi
    .fn<SyncEditorQuery>()
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce("accepted");
  const controller = new PreviewQueryController("wasm", frame(), vi.fn(), sync, vi.fn());

  controller.previewChanged("region=preview");
  const operationId = sync.mock.calls[0]?.[1];
  controller.editorChanged("region=editor", false);
  first.resolve("retry");
  controller.editorChanged("region=preview", false, operationId);
  controller.editorChanged("region=preview", false, operationId, true);
  await vi.advanceTimersByTimeAsync(1_000);

  expect(sync.mock.calls.map(([query]) => query)).toEqual(["?region=preview", "?region=editor"]);
  controller.cancel();
});

it("does not retry a cancelled write", async () => {
  vi.useFakeTimers();
  const pending = deferred();
  const sync = vi.fn<SyncEditorQuery>().mockReturnValue(pending.promise);
  const controller = new PreviewQueryController("wasm", frame(), vi.fn(), sync, vi.fn());

  controller.previewChanged("region=emea");
  controller.cancel();
  pending.resolve("retry");
  await pending.promise;
  await vi.runAllTimersAsync();

  expect(sync).toHaveBeenCalledTimes(1);
});
