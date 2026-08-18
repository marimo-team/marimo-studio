import assert from "node:assert/strict";
import { test } from "vite-plus/test";
import { z } from "zod";

import { loadRuntimeConfig } from "../src/runtime-config/index.ts";
import {
  readServerValues,
  readServerValuesWithRetry,
  ValueRequestError,
} from "../src/values/index.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
};

const config = {
  schema: 1,
  revision: "presentation-revision",
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    id: "server",
    instance: "server-instance",
    available: ["server", "wasm"],
    data: {
      fileKey: "/workspace/notebook.py",
      serverToken: "server-token",
      serverInstance: "server-instance",
      preserveSession: false,
      url: "/proxy/app/",
    },
  },
  rootUrl: "/proxy/app/",
  publicRootUrl: "/proxy/app/",
  documentRootUrl: "/proxy/app/",
  supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
  cellBindings: {},
  valueBindings: {
    "context.label": {
      variable: "context",
      cell: { kind: "id", value: "cell-id" },
    },
  },
  outputBindings: {},
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: false,
  mode: "run",
};

const requestUrl = (input: RequestInfo | URL): string =>
  input instanceof URL ? input.href : new Request(input).url;

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
    return Promise.resolve(Response.json({ values: { "context.label": "ready" }, errors: {} }));
  };
  try {
    const result = await readServerValues("session-id", {
      revision: "presentation-revision",
      selectors: ["context.label"],
    });
    assert.deepEqual(result.values, { "context.label": "ready" });
    assert.deepEqual(url, "http://localhost:3000/proxy/app/_marimo-studio/views/dashboard/values");
    assert.deepEqual(headers.get("Marimo-Session-Id"), "session-id");
    assert.deepEqual(headers.get("Marimo-Server-Token"), "server-token");
    assert.deepEqual(JSON.parse(body), {
      revision: "presentation-revision",
      selectors: ["context.label"],
    });
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
        readServerValuesWithRetry("session", {
          revision: "presentation-revision",
          selectors: ["context.label"],
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
