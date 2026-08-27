import { outputReadRequestSchema } from "@marimo-studio/protocol/output-read";
import { afterEach, expect, test, vi } from "vite-plus/test";

import type { OutputResponseReconciler } from "../src/outputs/reader";

import { createServerOutputReader } from "../src/outputs/remote";
import {
  commitRuntimeConfig,
  loadRuntimeConfig,
  type RuntimeConfig,
} from "../src/runtime-config/index";
import { projectionRequest, symbolicRuntimeFields } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "revision-a",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
  sessionId: "s_view01",
  runtimeSessionId: "s_abc123",
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
      capabilityToken: "presentation-capability",
      sessionId: "s_abc123",
      serverInstance: "server-instance",
      preserveSession: false,
      url: "/",
    },
  },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
  presentationSessionId: "s_view01",
  ...symbolicRuntimeFields,
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: false,
  mode: "run",
  showCellLogs: true,
} satisfies RuntimeConfig;

test("discards canceled queued output work before dispatch", async () => {
  globalThis.fetch = vi.fn(async () => Response.json(config));
  await loadRuntimeConfig();

  let releaseFirst = (_response: Response) => {};
  const firstResponse = new Promise<Response>((resolve) => {
    releaseFirst = resolve;
  });
  const requests: Array<{
    revision: string;
    selector: string;
    url: string;
  }> = [];
  globalThis.fetch = vi.fn(async (input, init) => {
    const body = outputReadRequestSchema.parse(JSON.parse(String(init?.body)));
    const selector = body.projections[0]?.target ?? "cleanup";
    requests.push({
      revision: body.revision,
      selector,
      url: String(input),
    });
    if (selector === "first") {
      return firstResponse;
    }
    return Response.json({
      outputs: {
        [selector]: {
          ownerCellId: `owner-${selector}`,
          mimetype: "text/plain",
          data: selector,
          timestamp: 2,
          resetUiObjectIds: [],
        },
      },
      errors: {},
    });
  });
  const reconcile = vi.fn<OutputResponseReconciler>((response) => response);
  const reader = createServerOutputReader("preview-a", reconcile);
  const controller = new AbortController();
  const firstProjection = projectionRequest("first", "output", "projection-first");
  const secondProjection = projectionRequest("second", "output", "projection-second");
  const thirdProjection = projectionRequest("third", "output", "projection-third");
  const first = reader({
    revision: "revision-a",
    projections: [firstProjection],
    activeProjections: [firstProjection],
  });
  const second = reader(
    {
      revision: "revision-a",
      projections: [secondProjection],
      activeProjections: [firstProjection, secondProjection],
    },
    controller.signal,
  );
  const third = reader({
    revision: "revision-a",
    projections: [thirdProjection],
    activeProjections: [firstProjection, thirdProjection],
  });

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
      data: { ...config.runtime.data, capabilityToken: "next-capability" },
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
  await expect(third).resolves.toMatchObject({ outputs: { third: { data: "third" } } });
  expect(requests.map(({ selector }) => selector)).toEqual(["first", "third"]);
  await vi.waitFor(() =>
    expect(reconcile).toHaveBeenCalledWith(
      expect.objectContaining({ outputs: { first: expect.objectContaining({ data: "first" }) } }),
    ),
  );
  expect(reconcile).toHaveBeenCalledTimes(2);
  expect(requests[1]).toMatchObject({
    revision: "revision-b",
  });
  expect(requests[1]?.url).toContain("/_marimo-studio/views/executive/outputs");
});
