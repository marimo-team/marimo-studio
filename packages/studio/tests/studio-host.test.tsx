import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";
import type { StudioHostBootstrap } from "@marimo-studio/protocol/studio-host";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vite-plus/test";

import { StudioHost } from "../src/app/StudioHost.tsx";

const host: StudioHostBootstrap = {
  schema: 1,
  state: "needs-view",
  defaultView: "dashboard",
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

const ready: StudioBootstrap = {
  schema: 1,
  notebook: { name: "analysis.py" },
  selectedView: "dashboard",
  views: ["dashboard"],
  runtimes: [{ id: "server", label: "Server" }],
  defaultRuntime: "server",
  clientId: host.clientId,
  serverInstance: host.serverInstance,
  serverToken: host.serverToken,
  urls: {
    editor: host.urls.editor,
    agent: "/_marimo-studio",
    events: "/_marimo-studio/dev/events",
    query: "/_marimo-studio/query",
    studioPrefix: "/studio/",
    viewPrefix: "/",
    viewSupportPrefix: "/_marimo-studio/views",
    views: "/_marimo-studio/views",
  },
  workspaceId: "workspace",
};

class EventSourceStub {
  addEventListener(): void {}
  close(): void {}
}

it("opens an already-created first view after a bootstrap retry", async () => {
  vi.stubGlobal("EventSource", EventSourceStub);
  let creates = 0;
  let bootstraps = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const source = input instanceof Request ? input.url : String(input);
      const url = new URL(source, globalThis.location.href);
      if (init?.method === "POST" && url.pathname.endsWith("/_marimo-studio/views")) {
        creates += 1;
        return Response.json({ schema: 1, name: "dashboard" }, { status: 201 });
      }
      if (url.pathname.endsWith("/_marimo-studio/bootstrap")) {
        bootstraps += 1;
        return bootstraps === 1
          ? Response.json(
              { error: "temporary", message: "Bootstrap is temporarily unavailable." },
              { status: 503 },
            )
          : Response.json(ready);
      }
      if (url.pathname.includes("/source/")) {
        return new Response("", { headers: { ETag: '"revision"' } });
      }
      throw new Error(`Unexpected request ${url}`);
    }),
  );
  const frameHost = document.createElement("div");
  const editorFrame = document.createElement("iframe");
  frameHost.append(editorFrame);
  document.body.append(frameHost);
  const publishBootstrap = vi.fn();
  const user = userEvent.setup();

  render(
    <StudioHost
      host={host}
      editorFrame={editorFrame}
      publishBootstrap={publishBootstrap}
      brand={{ marks: { dark: "dark.svg", light: "light.svg" } }}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Create dashboard" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Bootstrap is temporarily unavailable.",
  );
  await user.click(screen.getByRole("button", { name: "Open dashboard" }));
  await vi.waitFor(() => expect(publishBootstrap).toHaveBeenCalledWith(ready));

  expect(creates).toBe(1);
  expect(bootstraps).toBe(2);
  expect(editorFrame.parentElement).toBe(frameHost);
  frameHost.remove();
});
