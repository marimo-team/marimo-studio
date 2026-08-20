import { afterEach, expect, it, vi } from "vite-plus/test";

import type { RuntimeControlRequestError } from "../src/features/preview/control-remote.ts";

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
      "wasm",
      "s_123456",
      "revision-1",
      "browser-client-1234",
    ),
  ).rejects.toThrow("503");

  const requestedInput = fetch.mock.calls[0]?.[0];
  if (!(requestedInput instanceof URL)) {
    throw new TypeError("Expected the controls endpoint URL");
  }
  const requested = requestedInput;
  expect(requested.pathname).toBe("/_marimo-studio/views/dashboard/controls");
  expect(requested.searchParams.get("runtime")).toBe("wasm");
  expect(requested.searchParams.get("revision")).toBe("revision-1");
  expect(requested.searchParams.get("marimo_studio_client")).toBe("browser-client-1234");
  const headers = new Headers(fetch.mock.calls[0]?.[1]?.headers);
  expect(headers.get("Marimo-Session-Id")).toBe("s_123456");
});

it("uses ETags for unchanged control snapshots", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          schema: 1,
          revision: "revision-1",
          runtime: "server",
          controlRevision: 7,
          controls: { native: { cells: {} } },
        }),
        { headers: { ETag: '"controls-a"', "Content-Type": "application/json" } },
      ),
    )
    .mockResolvedValueOnce(new Response(null, { status: 304, headers: { ETag: '"controls-a"' } }));
  vi.stubGlobal("fetch", fetch);

  const changed = await fetchRuntimeControls(
    "/_marimo-studio/views/dashboard",
    "server",
    "s_123456",
    "revision-1",
    "browser-client-1234",
  );
  const unchanged = await fetchRuntimeControls(
    "/_marimo-studio/views/dashboard",
    "server",
    "s_123456",
    "revision-1",
    "browser-client-1234",
    changed.etag,
  );

  expect(changed).toMatchObject({ kind: "changed", etag: '"controls-a"' });
  expect(unchanged).toEqual({ kind: "unchanged", etag: '"controls-a"' });
  const conditionalHeaders = new Headers(fetch.mock.calls[1]?.[1]?.headers);
  expect(conditionalHeaders.get("If-None-Match")).toBe('"controls-a"');
});

it.each([
  ["runtime-sync-pending", true],
  ["presentation-revision-unavailable", true],
] as const)("parses bounded %s control errors", async (code, transient) => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({ error: code, message: `Control error ${code}`, transient }, { status: 409 }),
    ),
  );

  await expect(
    fetchRuntimeControls(
      "/_marimo-studio/views/dashboard",
      "server",
      "s_123456",
      "revision-1",
      "browser-client-1234",
    ),
  ).rejects.toMatchObject({
    code,
    message: `Control error ${code}`,
    status: 409,
    transient,
  });
});

it("rejects an oversized control error body without parsing it", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response("x".repeat(16 * 1024 + 1), {
          status: 409,
          headers: { "Content-Length": String(16 * 1024 + 1) },
        }),
    ),
  );

  await expect(
    fetchRuntimeControls(
      "/_marimo-studio/views/dashboard",
      "server",
      "s_123456",
      "revision-1",
      "browser-client-1234",
    ),
  ).rejects.toEqual(
    expect.objectContaining<Partial<RuntimeControlRequestError>>({
      code: "control-configuration-failed",
      status: 409,
    }),
  );
});
