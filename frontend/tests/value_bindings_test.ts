import { assertEquals, assertRejects } from "@std/assert";

import { loadRuntimeConfig } from "../src/runtime-config.ts";
import {
  readValues,
  readValuesWithRetry,
  ValueRequestError,
} from "../src/value-bindings.ts";

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

const installConfig = async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => Promise.resolve(Response.json(config));
  try {
    await loadRuntimeConfig();
  } finally {
    globalThis.fetch = originalFetch;
  }
};

Deno.test("value reads send exact selectors through the configured base URL", async () => {
  await installConfig();
  const originalFetch = globalThis.fetch;
  let url = "";
  let headers = new Headers();
  let body = "";
  globalThis.fetch = (input, init) => {
    url = String(input);
    headers = new Headers(init?.headers);
    body = String(init?.body);
    return Promise.resolve(
      Response.json({ values: { "context.label": "ready" }, errors: {} }),
    );
  };
  try {
    const result = await readValues("session-id", ["context.label"]);
    assertEquals(result.values, { "context.label": "ready" });
    assertEquals(url, "/proxy/app/_marimo-studio/views/dashboard/values");
    assertEquals(headers.get("Marimo-Session-Id"), "session-id");
    assertEquals(headers.get("Marimo-Server-Token"), "server-token");
    assertEquals(JSON.parse(body), { selectors: ["context.label"] });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

Deno.test("terminal value failures do not retry", async () => {
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
    await assertRejects(
      () => readValuesWithRetry("session", ["context.label"]),
      ValueRequestError,
      "Unknown selector",
    );
    assertEquals(requests, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
