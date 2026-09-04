import { describe, expect, it } from "vite-plus/test";

import { parseStudioBootstrap } from "../src/studio-bootstrap.ts";

const payload = {
  schema: 1,
  notebook: { name: "analysis.py" },
  defaultView: "dashboard",
  selectedView: "dashboard",
  views: ["dashboard"],
  runtimes: [{ id: "server", label: "Python" }],
  defaultRuntime: "server",
  clientId: "browser-client-1234",
  serverInstance: "server-instance",
  urls: {
    editor: "/_marimo-studio/editor/?file=analysis.py",
    agent: "/_marimo-studio",
    events: "/_marimo-studio/dev/events",
    query: "/_marimo-studio/query",
    studioPrefix: "/studio/",
    viewPrefix: "/",
    viewSupportPrefix: "/_marimo-studio/views",
    views: "/_marimo-studio/views",
  },
  workspaceId: "workspace",
  serverToken: "token",
};

describe("Studio bootstrap", () => {
  it("accepts the versioned document contract", () => {
    expect(parseStudioBootstrap(payload)).toEqual(payload);
  });

  it("rejects selected views and runtimes outside their declared lists", () => {
    expect(() => parseStudioBootstrap({ ...payload, selectedView: "missing" })).toThrow();
    expect(() => parseStudioBootstrap({ ...payload, defaultRuntime: "wasm" })).toThrow();
  });

  it("rejects duplicate view and runtime identities", () => {
    expect(() => parseStudioBootstrap({ ...payload, views: ["dashboard", "dashboard"] })).toThrow();
    expect(() =>
      parseStudioBootstrap({
        ...payload,
        runtimes: [payload.runtimes[0], payload.runtimes[0]],
      }),
    ).toThrow();
  });
});
