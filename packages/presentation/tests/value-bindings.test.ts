import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { loadRuntimeConfig } from "../src/runtime-config/index.ts";
import { readValues, readValuesWithRetry, ValueRequestError } from "../src/values/index.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
};

const config = {
  schema: 1,
  revision: "presentation-revision",
  view: "dashboard",
  views: ["dashboard"],
  fileKey: "/workspace/notebook.py",
  runtimeUrl: "/proxy/app/",
  supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
  cellBindings: {},
  valueBindings: {
    "context.label": {
      variable: "context",
      cell: { kind: "id", value: "cell-id" },
    },
  },
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  serverToken: "server-token",
  dev: false,
  mode: "run",
  preserveSession: false,
};

const requestUrl = (input: RequestInfo | URL): string => {
  if (typeof input === "string") {
    return input;
  }
  if (input instanceof URL) {
    return input.href;
  }
  return input.url;
};

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
    if (typeof init?.body !== "string") {
      throw new TypeError("Expected a JSON request body");
    }
    body = init.body;
    return Promise.resolve(Response.json({ values: { "context.label": "ready" }, errors: {} }));
  };
  try {
    const result = await readValues("session-id", ["context.label"]);
    assert.deepEqual(result.values, { "context.label": "ready" });
    assert.deepEqual(url, "/proxy/app/_marimo-studio/views/dashboard/values");
    assert.deepEqual(headers.get("Marimo-Session-Id"), "session-id");
    assert.deepEqual(headers.get("Marimo-Server-Token"), "server-token");
    assert.deepEqual(JSON.parse(body), { selectors: ["context.label"] });
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
      () => readValuesWithRetry("session", ["context.label"]),
      (error: unknown) => {
        assert.ok(error instanceof ValueRequestError);
        assert.match(error.message, /Unknown selector/);
        return true;
      },
    );
    assert.deepEqual(requests, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
