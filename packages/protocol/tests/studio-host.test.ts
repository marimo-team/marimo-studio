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
    bootstrap: "/_marimo-studio/bootstrap",
    editor: "/_marimo-studio/editor/?file=analysis.py",
    events: "/_marimo-studio/dev/events",
    views: "/_marimo-studio/views",
  },
};

describe("Studio host bootstrap", () => {
  it("accepts every workspace lifecycle that preserves the editor", () => {
    expect(parseStudioHostBootstrap(payload).state).toBe("unconfigured");
    expect(
      parseStudioHostBootstrap({
        ...payload,
        state: "needs-view",
        defaultView: "dashboard",
        generation: "a".repeat(64),
      }).state,
    ).toBe("needs-view");
    expect(parseStudioHostBootstrap({ ...payload, state: "ready" }).state).toBe("ready");
  });

  it("requires the first view in needs-view state", () => {
    expect(() => parseStudioHostBootstrap({ ...payload, state: "needs-view" })).toThrow();
    expect(() =>
      parseStudioHostBootstrap({
        ...payload,
        state: "needs-view",
        defaultView: "dashboard",
        generation: "stale",
      }),
    ).toThrow();
  });
});
