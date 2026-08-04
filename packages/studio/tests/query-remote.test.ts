import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import { syncEditorQuery } from "../src/preview/query-remote";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("editor query synchronization", () => {
  it("posts to the configured query route", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 202 }));
    vi.stubGlobal("fetch", fetch);

    await syncEditorQuery("/_marimo-studio/query", "token", "region=emea");

    expect(fetch).toHaveBeenCalledWith(
      "/_marimo-studio/query",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ query: "region=emea" }),
      }),
    );
  });
});
