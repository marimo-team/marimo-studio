import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import { syncEditorQuery } from "../src/features/preview/query-remote";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("editor query synchronization", () => {
  it("posts to the configured query route", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 202 }));
    vi.stubGlobal("fetch", fetch);

    const result = await syncEditorQuery(
      "/_marimo-studio/query",
      "token",
      "browser-client-1234",
      "region=emea",
      "query-1",
      7,
    );

    expect(fetch).toHaveBeenCalledWith(
      "/_marimo-studio/query",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          clientId: "browser-client-1234",
          operationId: "query-1",
          query: "region=emea",
          writeGeneration: 7,
        }),
      }),
    );
    expect(result).toBe("accepted");
  });

  it("waits for the accepted response to finish", async () => {
    let finish!: () => void;
    let reading!: () => void;
    const bodyRead = new Promise<void>((resolve) => {
      reading = resolve;
    });
    const response = new Response(
      new ReadableStream(
        {
          start(controller) {
            finish = () => controller.close();
          },
          pull() {
            reading();
          },
        },
        { highWaterMark: 0 },
      ),
      { status: 202 },
    );
    const fetch = vi.fn().mockResolvedValue(response);
    vi.stubGlobal("fetch", fetch);
    const completed = vi.fn();
    const pending = syncEditorQuery(
      "/query",
      "token",
      "browser-client-1234",
      "region=emea",
      "query-1",
      7,
    ).then(completed);
    try {
      await Promise.race([bodyRead, pending]);
      expect(completed).not.toHaveBeenCalled();
    } finally {
      finish();
      await pending;
    }
    expect(completed).toHaveBeenCalledWith("accepted");
  });

  it("returns a retry outcome for an explicit transient response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ transient: true }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      syncEditorQuery("/query", "token", "browser-client-1234", "region=emea", "query-1", 7),
    ).resolves.toBe("retry");
  });

  it.each([408, 429, 503])("returns a retry outcome for HTTP %s", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status })));

    await expect(
      syncEditorQuery("/query", "token", "browser-client-1234", "region=emea", "query-1", 7),
    ).resolves.toBe("retry");
  });

  it("returns a retry outcome after a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));

    await expect(
      syncEditorQuery("/query", "token", "browser-client-1234", "region=emea", "query-1", 7),
    ).resolves.toBe("retry");
  });

  it("bounds a stalled request and returns a retry outcome", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        });
      }),
    );

    const pending = expect(
      syncEditorQuery("/query", "token", "browser-client-1234", "region=emea", "query-1", 7),
    ).resolves.toBe("retry");
    await vi.advanceTimersByTimeAsync(3_000);

    await pending;
  });

  it("keeps the attempt deadline active while reading an error body", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        const response = new Response(null, { status: 409 });
        vi.spyOn(response, "json").mockImplementation(
          () =>
            new Promise<never>((_resolve, reject) => {
              init?.signal?.addEventListener(
                "abort",
                () => reject(new DOMException("Aborted", "AbortError")),
                { once: true },
              );
            }),
        );
        return Promise.resolve(response);
      }),
    );

    const pending = expect(
      syncEditorQuery("/query", "token", "browser-client-1234", "region=emea", "query-1", 7),
    ).resolves.toBe("retry");
    await vi.advanceTimersByTimeAsync(3_000);

    await pending;
  });

  it("preserves caller cancellation", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        });
      }),
    );

    const request = syncEditorQuery(
      "/query",
      "token",
      "browser-client-1234",
      "region=emea",
      "query-1",
      7,
      controller.signal,
    );
    const cancelled = expect(request).rejects.toThrow("Aborted");
    controller.abort();

    await cancelled;
  });

  it("rejects a permanent error response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ transient: false }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      syncEditorQuery("/query", "token", "browser-client-1234", "region=emea", "query-1", 7),
    ).rejects.toThrow("failed with 409");
  });
});
