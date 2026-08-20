import { expect, it, vi } from "vite-plus/test";

import { runRuntimeQuery } from "../src/runtime/runtime.tsx";

it("cancels a stalled runtime query callback through the adapter signal", async () => {
  const update = vi.fn(
    async (_invoke, _query: string, signal: AbortSignal) =>
      await new Promise<void>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      }),
  );
  const invoke = vi.fn(async () => null);
  const controller = new AbortController();

  const querying = runRuntimeQuery(update, invoke, "?mode=stalled", controller.signal);
  const cancelled = expect(querying).rejects.toMatchObject({ name: "AbortError" });
  await vi.waitFor(() => expect(update).toHaveBeenCalledOnce());
  controller.abort(new DOMException("Runtime disposed", "AbortError"));

  await cancelled;
});
