import { afterEach, expect, it, vi } from "vite-plus/test";

import type { EditorQuerySyncResult } from "../src/features/preview/query-remote.ts";

import { PreviewQueryController } from "../src/features/preview/query-controller.ts";

afterEach(() => {
  vi.useRealTimers();
});

const deferred = () => {
  let resolve!: (result: EditorQuerySyncResult) => void;
  const promise = new Promise<EditorQuerySyncResult>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

const frame = () => document.createElement("iframe");

it("applies an editor query through the rendered preview API", async () => {
  const preview = frame();
  document.body.append(preview);
  const child = preview.contentWindow;
  if (!child) {
    throw new Error("The preview iframe did not create a window");
  }
  const updateQuery = vi.fn(async (_query: string) => {});
  Object.defineProperty(child, "marimoStudio", {
    configurable: true,
    value: {
      ready: async () => {},
      updateQuery,
    },
  });
  const controller = new PreviewQueryController("wasm", preview, vi.fn(), vi.fn(), vi.fn());

  controller.editorChanged("region=emea", true);

  await vi.waitFor(() => expect(updateQuery).toHaveBeenCalledWith("?region=emea"));
  controller.cancel();
  preview.remove();
});

it("serializes writes and coalesces them to the latest query", async () => {
  const first = deferred();
  const second = deferred();
  const sync = vi
    .fn<
      (query: string, operationId: string, signal: AbortSignal) => Promise<EditorQuerySyncResult>
    >()
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
    .fn<
      (query: string, operationId: string, signal: AbortSignal) => Promise<EditorQuerySyncResult>
    >()
    .mockResolvedValueOnce("retry")
    .mockResolvedValueOnce("accepted");
  const controller = new PreviewQueryController("wasm", frame(), vi.fn(), sync, vi.fn());

  controller.previewChanged("region=emea");
  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(1));
  await vi.advanceTimersByTimeAsync(1_000);

  expect(sync).toHaveBeenCalledTimes(2);
  expect(sync.mock.calls.map(([query]) => query)).toEqual(["?region=emea", "?region=emea"]);
  expect(sync.mock.calls[1]?.[1]).toBe(sync.mock.calls[0]?.[1]);
  controller.cancel();
});

it("applies a newer editor query after an accepted preview write", async () => {
  const first = deferred();
  const sync = vi
    .fn<
      (query: string, operationId: string, signal: AbortSignal) => Promise<EditorQuerySyncResult>
    >()
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce("accepted");
  const controller = new PreviewQueryController("wasm", frame(), vi.fn(), sync, vi.fn());

  controller.previewChanged("region=preview");
  controller.editorChanged("region=editor", false);
  first.resolve("accepted");

  await vi.waitFor(() => expect(sync).toHaveBeenCalledTimes(2));
  expect(sync.mock.calls.map(([query]) => query)).toEqual(["?region=preview", "?region=editor"]);
  controller.cancel();
});

it("preserves newer editor intent across a delayed preview echo", async () => {
  const first = deferred();
  const sync = vi
    .fn<
      (query: string, operationId: string, signal: AbortSignal) => Promise<EditorQuerySyncResult>
    >()
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
    .fn<
      (query: string, operationId: string, signal: AbortSignal) => Promise<EditorQuerySyncResult>
    >()
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
    .fn<
      (query: string, operationId: string, signal: AbortSignal) => Promise<EditorQuerySyncResult>
    >()
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

it("replaces a stale retry with a newer editor query", async () => {
  vi.useFakeTimers();
  const first = deferred();
  const sync = vi
    .fn<
      (query: string, operationId: string, signal: AbortSignal) => Promise<EditorQuerySyncResult>
    >()
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce("accepted");
  const controller = new PreviewQueryController("wasm", frame(), vi.fn(), sync, vi.fn());

  controller.previewChanged("region=preview");
  controller.editorChanged("region=editor", false);
  first.resolve("retry");
  await vi.advanceTimersByTimeAsync(1_000);

  expect(sync.mock.calls.map(([query]) => query)).toEqual(["?region=preview", "?region=editor"]);
  controller.cancel();
});

it("does not retry a cancelled write", async () => {
  vi.useFakeTimers();
  const pending = deferred();
  const sync = vi
    .fn<
      (query: string, operationId: string, signal: AbortSignal) => Promise<EditorQuerySyncResult>
    >()
    .mockReturnValue(pending.promise);
  const controller = new PreviewQueryController("wasm", frame(), vi.fn(), sync, vi.fn());

  controller.previewChanged("region=emea");
  controller.cancel();
  pending.resolve("retry");
  await pending.promise;
  await vi.runAllTimersAsync();

  expect(sync).toHaveBeenCalledTimes(1);
});
