import { afterEach, expect, it, vi } from "vite-plus/test";

import type { fetchRuntimeControls } from "../src/features/preview/control-remote.ts";

import { changed, createControlController, endpoint } from "./control-controller-fixture.ts";

afterEach(() => {
  vi.useRealTimers();
});

it("continues polling after one controls request times out", async () => {
  vi.useFakeTimers();
  let calls = 0;
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(
    async (_support, runtime, _session, _revision, _client, etag, signal) => {
      calls += 1;
      if (calls <= 2) {
        return changed({
          schema: 1,
          revision: "revision-1",
          runtime,
          controls: { native: { cells: {} } },
        });
      }
      if (calls === 3) {
        return await new Promise<never>((_resolve, reject) => {
          signal?.addEventListener("abort", () => reject(signal.reason), { once: true });
        });
      }
      return { kind: "unchanged", etag: etag ?? '"etag-1"' };
    },
  );
  const connect = vi.fn(() => endpoint());
  const { controller } = createControlController({ connect, fetchControls });

  controller.begin("revision-1", "s_123456");
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));
  await vi.advanceTimersByTimeAsync(1_000);
  await vi.advanceTimersByTimeAsync(3_000);
  await vi.advanceTimersByTimeAsync(1_000);
  await vi.waitFor(() => expect(fetchControls).toHaveBeenCalledTimes(6));

  expect(connect).toHaveBeenCalledTimes(2);
  controller.stop();
});

it("drops conditional request state across revision and session turnover", async () => {
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(
    async (_support, runtime, _session, revision) =>
      changed({
        schema: 1,
        revision,
        runtime,
        controls: { native: { cells: {} } },
      }),
  );
  const connect = vi.fn(() => endpoint());
  const { controller } = createControlController({ connect, fetchControls });

  for (const [index, [revision, session]] of [
    ["revision-1", "s_123456"],
    ["revision-2", "s_123456"],
    ["revision-2", "s_654321"],
  ].entries()) {
    controller.begin(revision, session);
    await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes((index + 1) * 2));
    controller.stop();
  }

  expect(fetchControls).toHaveBeenCalledTimes(6);
  expect(fetchControls.mock.calls.every((call) => call[5] === undefined)).toBe(true);
});
