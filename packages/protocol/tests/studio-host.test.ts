import { describe, expect, it } from "vite-plus/test";

import { parseStudioHostBootstrap } from "../src/studio-host.ts";

const payload = {
  schema: 1,
  state: "unconfigured",
  notebook: { name: "analysis.py" },
  clientId: "browser-client-1234",
  serverInstance: "server-instance",
  serverToken: "token",
  urls: {
    bootstrap: "./_marimo-studio/bootstrap",
    editor: "./_marimo-studio/editor/?file=analysis.py",
    events: "./_marimo-studio/dev/events",
    views: "./_marimo-studio/views",
  },
};

// A proxy serves the notebook root beneath a prefix that the server never sees.
const documentUrl = "https://workbench.example/s/f3a9/p/77c1/";

describe("Studio host bootstrap", () => {
  it("accepts every workspace lifecycle that preserves the editor", () => {
    expect(parseStudioHostBootstrap(payload, documentUrl).state).toBe("unconfigured");
    expect(
      parseStudioHostBootstrap(
        {
          ...payload,
          state: "needs-view",
          defaultView: "dashboard",
          generation: "a".repeat(64),
        },
        documentUrl,
      ).state,
    ).toBe("needs-view");
    expect(parseStudioHostBootstrap({ ...payload, state: "ready" }, documentUrl).state).toBe(
      "ready",
    );
  });

  it("resolves its URLs against the document that carried it", () => {
    expect(parseStudioHostBootstrap(payload, documentUrl).urls).toEqual({
      bootstrap: "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/bootstrap",
      editor: "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/editor/?file=analysis.py",
      events: "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/dev/events",
      views: "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/views",
    });
  });

  it("requires the first view in needs-view state", () => {
    expect(() =>
      parseStudioHostBootstrap({ ...payload, state: "needs-view" }, documentUrl),
    ).toThrow();
    expect(() =>
      parseStudioHostBootstrap(
        {
          ...payload,
          state: "needs-view",
          defaultView: "dashboard",
          generation: "stale",
        },
        documentUrl,
      ),
    ).toThrow();
  });
});
