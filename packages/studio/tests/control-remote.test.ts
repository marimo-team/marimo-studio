import { afterEach, expect, it, vi } from "vite-plus/test";

import { fetchRuntimeControls } from "../src/features/preview/control-remote.ts";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("targets control configuration at the active editor session", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 503 }));
  vi.stubGlobal("fetch", fetch);

  await expect(
    fetchRuntimeControls(
      "/_marimo-studio/views/dashboard",
      "browser-client-1234",
      "s_123456",
      "revision-1",
    ),
  ).rejects.toThrow("503");

  const url = new URL(String(fetch.mock.calls[0]?.[0]));
  expect(url.pathname).toBe("/_marimo-studio/views/dashboard/controls");
  expect(url.searchParams.get("marimo_studio_client")).toBe("browser-client-1234");
  expect(url.searchParams.get("revision")).toBe("revision-1");
  expect(fetch).toHaveBeenCalledWith(
    expect.any(URL),
    expect.objectContaining({
      headers: { "Marimo-Session-Id": "s_123456" },
    }),
  );
});
