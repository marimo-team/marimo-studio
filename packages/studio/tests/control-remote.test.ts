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
      "http://localhost:3000/_marimo-studio/views/dashboard",
      "browser-client-1234",
      "s_123456",
      "revision-1",
    ),
  ).rejects.toMatchObject({ code: "control-request-failed", transient: true });

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

it("preserves an abort while reading a control error response", async () => {
  const controller = new AbortController();
  const response = new Response(null, { status: 503 });
  response.json = vi.fn().mockRejectedValue(new DOMException("aborted", "AbortError"));
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
  controller.abort();

  await expect(
    fetchRuntimeControls(
      "http://localhost:3000/views/dashboard",
      "client",
      "s_123456",
      "revision",
      controller.signal,
    ),
  ).rejects.toMatchObject({ name: "AbortError" });
});

it("preserves terminal runtime synchronization diagnostics", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      Response.json(
        {
          error: "runtime-sync-required",
          message: "Run the changed notebook cells to update the Python runtime preview.",
          transient: false,
          hint: "Run the changed notebook cells in the editor, then retry the preview.",
        },
        { status: 409 },
      ),
    ),
  );

  await expect(
    fetchRuntimeControls("http://localhost:3000/views/dashboard", "client", "s_123456", "revision"),
  ).rejects.toMatchObject({
    name: "ControlRequestError",
    code: "runtime-sync-required",
    transient: false,
    hint: "Run the changed notebook cells in the editor, then retry the preview.",
  });
});
