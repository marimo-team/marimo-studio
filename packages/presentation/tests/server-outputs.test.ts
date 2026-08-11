import { reconcileProjectedOutput } from "@marimo-studio/marimo-frontend/projected-output";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { createServerOutputReader } from "../src/outputs/remote";
import {
  commitRuntimeConfig,
  loadRuntimeConfig,
  type RuntimeConfig,
} from "../src/runtime-config/index";

vi.mock("@marimo-studio/marimo-frontend/projected-output", () => ({
  reconcileProjectedOutput: vi.fn(),
}));

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "revision-a",
  runtime: "server",
};

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.clearAllMocks();
});

const config = {
  schema: 1,
  revision: "revision-a",
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    id: "server",
    instance: "server-instance",
    available: ["server"],
    data: {
      fileKey: "/workspace/notebook.py",
      serverToken: "server-token",
      preserveSession: false,
      url: "/",
    },
  },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
  cellBindings: {},
  valueBindings: {},
  outputBindings: {
    first: { variable: "first", cell: { kind: "id", value: "cell-id" } },
    second: { variable: "second", cell: { kind: "id", value: "cell-id" } },
  },
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: false,
  mode: "run",
  showCellLogs: true,
} satisfies RuntimeConfig;

test("serializes server output work without retaining a canceled response", async () => {
  globalThis.fetch = vi.fn(async () => Response.json(config));
  await loadRuntimeConfig();

  let releaseFirst = (_response: Response) => {};
  const firstResponse = new Promise<Response>((resolve) => {
    releaseFirst = resolve;
  });
  const requests: Array<{ revision: string; selector: string; token: string | null; url: string }> =
    [];
  globalThis.fetch = vi.fn(async (input, init) => {
    const body = JSON.parse(String(init?.body)) as {
      revision: string;
      selectors: string[];
    };
    const selector = body.selectors[0] ?? "cleanup";
    requests.push({
      revision: body.revision,
      selector,
      token: new Headers(init?.headers).get("Marimo-Server-Token"),
      url: String(input),
    });
    if (selector === "first") {
      return firstResponse;
    }
    return Response.json({
      outputs: {
        second: {
          ownerCellId: "owner-second",
          mimetype: "text/plain",
          data: "second",
          timestamp: 2,
          resetUiObjectIds: [],
        },
      },
      errors: {},
    });
  });
  const reader = createServerOutputReader("preview-a");
  const controller = new AbortController();
  const first = reader({
    revision: "revision-a",
    selectors: ["first"],
    activeSelectors: ["first"],
  });
  const second = reader(
    { revision: "revision-a", selectors: ["second"], activeSelectors: ["first", "second"] },
    controller.signal,
  );

  await vi.waitFor(() => expect(requests.map(({ selector }) => selector)).toEqual(["first"]));
  controller.abort();
  await expect(second).rejects.toMatchObject({ name: "AbortError" });
  commitRuntimeConfig({
    ...config,
    revision: "revision-b",
    view: "executive",
    supportUrl: "/_marimo-studio/views/executive",
    runtime: {
      ...config.runtime,
      data: { ...config.runtime.data, serverToken: "next-server-token" },
    },
  });
  releaseFirst(
    Response.json({
      outputs: {
        first: {
          ownerCellId: "owner-first",
          mimetype: "text/plain",
          data: "first",
          timestamp: 1,
          resetUiObjectIds: [],
        },
      },
      errors: {},
    }),
  );

  await expect(first).resolves.toMatchObject({ outputs: { first: { data: "first" } } });
  await vi.waitFor(() =>
    expect(requests.map(({ selector }) => selector)).toEqual(["first", "second"]),
  );
  await vi.waitFor(() =>
    expect(reconcileProjectedOutput).toHaveBeenCalledWith(
      expect.objectContaining({ data: "first" }),
    ),
  );
  expect(reconcileProjectedOutput).not.toHaveBeenCalledWith(
    expect.objectContaining({ data: "second" }),
  );
  expect(requests[1]).toMatchObject({
    revision: "revision-a",
    token: "server-token",
  });
  expect(requests[1]?.url).toContain("/_marimo-studio/views/dashboard/outputs");
});
