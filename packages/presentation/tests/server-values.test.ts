import assert from "node:assert/strict";
import { test } from "vite-plus/test";
import { z } from "zod";

import { projectionWireRequest } from "../src/projections/identity.ts";
import { bindProjectionBindingStale } from "../src/projections/staleness.ts";
import { loadRuntimeConfig } from "../src/runtime-config/index.ts";
import {
  readServerValues,
  readServerValuesWithRetry,
  ValueRequestError,
} from "../src/values/remote.ts";
import { ARROW_FINGERPRINT, arrowBytes } from "./arrow-fixture.ts";
import { projectionRequest, symbolicRuntimeFields } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
  sessionId: "s_view01",
  runtimeSessionId: "s_abc123",
};

const config = {
  schema: 1,
  revision: "presentation-revision",
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    id: "server",
    instance: "server-instance",
    data: {
      fileKey: "/workspace/notebook.py",
      capabilityToken: "presentation-capability",
      sessionId: "s_abc123",
      serverInstance: "server-instance",
      preserveSession: false,
      url: "/proxy/app/",
    },
  },
  rootUrl: "/proxy/app/",
  publicRootUrl: "/proxy/app/",
  documentRootUrl: "/proxy/app/",
  supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
  presentationSessionId: "s_view01",
  showCellLogs: true,
  ...symbolicRuntimeFields,
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: false,
  mode: "run",
};

const requestUrl = (input: RequestInfo | URL): string => {
  if (input instanceof Request) {
    return input.url;
  }
  return new URL(input, globalThis.location.href).href;
};

const jsonValue = (value: string) => ({
  codec: "json-v1" as const,
  fingerprint: `sha256:${"0".repeat(64)}`,
  value,
});

const installConfig = async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => Promise.resolve(Response.json(config));
  try {
    await loadRuntimeConfig();
  } finally {
    globalThis.fetch = originalFetch;
  }
};

test("value reads send exact selectors through the configured base URL", async () => {
  await installConfig();
  const originalFetch = globalThis.fetch;
  let url = "";
  let headers = new Headers();
  let body = "";
  globalThis.fetch = (input, init) => {
    url = requestUrl(input);
    headers = new Headers(init?.headers);
    const parsedBody = z.string().safeParse(init?.body);
    if (!parsedBody.success) {
      throw new TypeError("Expected a JSON request body");
    }
    body = parsedBody.data;
    return Promise.resolve(
      Response.json({ values: { "context.label": jsonValue("ready") }, errors: {} }),
    );
  };
  try {
    const result = await readServerValues({
      revision: "presentation-revision",
      projections: [projectionRequest("context.label", "value")],
      activeProjections: [projectionRequest("context.label", "value")],
    });
    assert.deepEqual(result.values["context.label"], jsonValue("ready"));
    assert.deepEqual(url, "http://localhost:3000/proxy/app/_marimo-studio/views/dashboard/values");
    assert.deepEqual(headers.get("Marimo-Session-Id"), "s_view01");
    assert.equal(headers.get("Marimo-Server-Token"), null);
    assert.deepEqual(JSON.parse(body), {
      revision: "presentation-revision",
      projections: [projectionWireRequest(projectionRequest("context.label", "value"))],
      activeProjections: [projectionWireRequest(projectionRequest("context.label", "value"))],
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("value reads resolve Arrow resources to Flechette tables", async () => {
  await installConfig();
  const bytes = arrowBytes();
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = (input) => {
    const url = requestUrl(input);
    requests.push(url);
    if (url.endsWith("/@file/frame.arrow")) {
      return Promise.resolve(new Response(bytes.buffer));
    }
    return Promise.resolve(
      Response.json({
        values: {
          frame: {
            codec: "arrow-ipc-v1",
            fingerprint: ARROW_FINGERPRINT,
            dataUrl: "./@file/frame.arrow",
            byteLength: bytes.byteLength,
          },
        },
        errors: {},
      }),
    );
  };
  try {
    const result = await readServerValues({
      revision: "presentation-revision",
      projections: [projectionRequest("frame", "value")],
      activeProjections: [projectionRequest("frame", "value")],
    });
    const frame = result.values.frame;

    assert.equal(frame?.codec, "arrow-ipc-v1");
    assert.deepEqual(requests, [
      "http://localhost:3000/proxy/app/_marimo-studio/views/dashboard/values",
      "http://localhost:3000/proxy/app/@file/frame.arrow",
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("value reads retry an Arrow resource that is not yet published", async () => {
  await installConfig();
  const bytes = arrowBytes();
  const originalFetch = globalThis.fetch;
  let reads = 0;
  let resources = 0;
  globalThis.fetch = (input) => {
    const url = requestUrl(input);
    if (url.endsWith("/@file/retry.arrow")) {
      resources += 1;
      return Promise.resolve(
        resources === 1 ? new Response(null, { status: 404 }) : new Response(bytes.buffer),
      );
    }
    reads += 1;
    return Promise.resolve(
      Response.json({
        values: {
          retryFrame: {
            codec: "arrow-ipc-v1",
            fingerprint: ARROW_FINGERPRINT,
            dataUrl: "./@file/retry.arrow",
            byteLength: bytes.byteLength,
          },
        },
        errors: {},
      }),
    );
  };
  const projection = projectionRequest("retryFrame", "value");
  try {
    const result = await readServerValuesWithRetry({
      revision: "presentation-revision",
      projections: [projection],
      activeProjections: [projection],
    });

    assert.equal(result.values.retryFrame?.codec, "arrow-ipc-v1");
    assert.equal(reads, 2);
    assert.equal(resources, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("value reads retry a transient request network failure", async () => {
  await installConfig();
  const originalFetch = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = () => {
    requests += 1;
    return requests === 1
      ? Promise.reject(new TypeError("connection reset"))
      : Promise.resolve(
          Response.json({
            values: { networkRetry: jsonValue("ready") },
            errors: {},
          }),
        );
  };
  const projection = projectionRequest("networkRetry", "value");
  try {
    const result = await readServerValuesWithRetry({
      revision: "presentation-revision",
      projections: [projection],
      activeProjections: [projection],
    });

    assert.deepEqual(result.values.networkRetry, jsonValue("ready"));
    assert.equal(requests, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("terminal value failures do not retry", async () => {
  await installConfig();
  const originalFetch = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = () => {
    requests += 1;
    return Promise.resolve(
      Response.json(
        {
          error: "unknown-selector",
          message: "Unknown selector",
          transient: false,
        },
        { status: 400 },
      ),
    );
  };
  try {
    await assert.rejects(
      () =>
        readServerValuesWithRetry({
          revision: "presentation-revision",
          projections: [projectionRequest("context.label", "value")],
          activeProjections: [projectionRequest("context.label", "value")],
        }),
      (cause: unknown) => {
        assert.ok(cause instanceof ValueRequestError);
        assert.match(cause.message, /Unknown selector/);
        return true;
      },
    );
    assert.deepEqual(requests, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("a stale live binding requests a presentation refresh", async () => {
  await installConfig();
  const originalFetch = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = () => {
    requests += 1;
    return Promise.resolve(
      Response.json(
        {
          error: "stale-projection-binding",
          message: "The projection binding changed.",
          transient: false,
        },
        { status: 409 },
      ),
    );
  };
  let refreshes = 0;
  const unbind = bindProjectionBindingStale(() => {
    refreshes += 1;
  });
  try {
    await assert.rejects(() =>
      readServerValues({
        revision: "presentation-revision",
        projections: [projectionRequest("context.label", "value")],
        activeProjections: [projectionRequest("context.label", "value")],
      }),
    );
    await assert.rejects(() =>
      readServerValues({
        revision: "presentation-revision",
        projections: [projectionRequest("context.label", "value")],
        activeProjections: [projectionRequest("context.label", "value")],
      }),
    );
    assert.equal(refreshes, 1);
    assert.equal(requests, 1);
  } finally {
    unbind();
    globalThis.fetch = originalFetch;
  }
});
