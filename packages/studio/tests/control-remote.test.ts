import { afterEach, expect, it, vi } from "vite-plus/test";

import { fetchRuntimeControls } from "../src/features/preview/control-remote.ts";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("targets control configuration at the active editor session", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 503 }));
  vi.stubGlobal("fetch", fetch);

  await expect(
    fetchRuntimeControls("/_marimo-studio/views/dashboard", "wasm", "s_123456"),
  ).rejects.toThrow("503");

  expect(fetch).toHaveBeenCalledWith(
    expect.any(URL),
    expect.objectContaining({
      headers: { "Marimo-Session-Id": "s_123456" },
    }),
  );
});
