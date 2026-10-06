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
  trustedServerRuntime: false,
  clientId: "browser-client-1234",
  serverInstance: "server-instance",
  urls: {
    editor: "../../_marimo-studio/editor/?file=analysis.py",
    agent: "../../_marimo-studio",
    events: "../../_marimo-studio/dev/events",
    query: "../../_marimo-studio/query",
    studioPrefix: "../../studio/",
    viewPrefix: "../../",
    viewSupportPrefix: "../../_marimo-studio/views",
    views: "../../_marimo-studio/views",
  },
  workspaceId: "workspace",
  serverToken: "token",
};

// A proxy serves the workspace beneath a prefix that the server never sees.
const documentUrl = "https://workbench.example/s/f3a9/p/77c1/studio/dashboard/";

describe("Studio bootstrap", () => {
  it("resolves its URLs against the document that carried it", () => {
    expect(parseStudioBootstrap(payload, documentUrl)).toEqual({
      ...payload,
      urls: {
        editor: "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/editor/?file=analysis.py",
        agent: "https://workbench.example/s/f3a9/p/77c1/_marimo-studio",
        events: "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/dev/events",
        query: "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/query",
        studioPrefix: "https://workbench.example/s/f3a9/p/77c1/studio/",
        viewPrefix: "https://workbench.example/s/f3a9/p/77c1/",
        viewSupportPrefix: "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/views",
        views: "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/views",
      },
    });
  });

  it("defaults the trusted runtime flag for older backends", () => {
    const { trustedServerRuntime: _trustedServerRuntime, ...legacyPayload } = payload;
    expect(parseStudioBootstrap(legacyPayload, documentUrl).trustedServerRuntime).toBe(false);
  });

  it("rejects selected views and runtimes outside their declared lists", () => {
    expect(() =>
      parseStudioBootstrap({ ...payload, selectedView: "missing" }, documentUrl),
    ).toThrow();
    expect(() =>
      parseStudioBootstrap({ ...payload, defaultRuntime: "wasm" }, documentUrl),
    ).toThrow();
  });

  it("rejects duplicate view and runtime identities", () => {
    expect(() =>
      parseStudioBootstrap({ ...payload, views: ["dashboard", "dashboard"] }, documentUrl),
    ).toThrow();
    expect(() =>
      parseStudioBootstrap(
        {
          ...payload,
          runtimes: [payload.runtimes[0], payload.runtimes[0]],
        },
        documentUrl,
      ),
    ).toThrow();
  });
});
