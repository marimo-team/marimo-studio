import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";
import type { StudioHostBootstrap } from "@marimo-studio/protocol/studio-host";

import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vite-plus/test";
import { z } from "zod";

import { StudioHost } from "../src/app/StudioHost.tsx";
import { starter, componentStarter, unbuiltView, viewList } from "./fixtures.ts";
import { deferred } from "./studio-test-support.ts";

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

const createViewBodySchema = z.object({ starter: z.string() });

class EventSourceStub {
  addEventListener(): void {}
  close(): void {}
}

const trustedEditorSource =
  "editor/?file=analysis.py&marimo_studio_client=browser-client-1234&marimo_studio_server=server-instance&session_id=s_editor1&marimo_studio_editor=editor-capability";
const activationHost: StudioHostBootstrap = {
  schema: 1,
  state: "unconfigured",
  notebook: host.notebook,
  clientId: host.clientId,
  serverInstance: host.serverInstance,
  serverToken: host.serverToken,
  urls: {
    ...host.urls,
    bootstrap: `${host.urls.bootstrap}?region=initial`,
    editor: trustedEditorSource,
  },
};
const sourceProject = {
  schema: 1 as const,
  view: "dashboard",
  provider: "marimo-studio/vanilla",
  provider_options: {},
  documents: [{ path: "index.html", language: "html", access: "edit" as const }],
  mounts: [],
  diagnostics: [],
  build: unbuiltView,
  artifact: null,
};
let activationListener: ((event: Event) => void) | undefined;

class ActivationEventSource {
  addEventListener(type: string, listener: (event: Event) => void): void {
    if (type === "activate") {
      activationListener = listener;
    }
  }
  close(): void {}
}

const useActivationEvents = () => {
  activationListener = undefined;
  vi.stubGlobal("EventSource", ActivationEventSource);
};

const activateFirstView = async () => {
  await vi.waitFor(() => expect(activationListener).toBeDefined());
  await act(async () => {
    activationListener?.(
      new MessageEvent("activate", {
        data: JSON.stringify({ schema: 1, generation: 7, view: "dashboard" }),
      }),
    );
  });
};

const mountActiveEditor = (query = "", hash = "") => {
  const editorFrame = document.createElement("iframe");
  const source = new URL(trustedEditorSource, globalThis.location.href);
  for (const [key, value] of new URLSearchParams(query)) {
    source.searchParams.append(key, value);
  }
  source.hash = hash;
  editorFrame.src = source.href;
  document.body.append(editorFrame);
  const editorWindow = editorFrame.contentWindow;
  if (!editorWindow) {
    throw new Error("Test editor window did not mount.");
  }
  const live = new URL(editorWindow.location.href);
  live.searchParams.delete("session_id");
  editorWindow.history.replaceState(
    editorWindow.history.state,
    "",
    `${live.pathname}${live.search}${live.hash}`,
  );
  return { editorFrame, editorWindow };
};

const configuredEditorUrl = (editorFrame: HTMLIFrameElement, editorWindow: Window): URL => {
  const source = new URL(editorWindow.location.href);
  const sessionId = new URL(editorFrame.src).searchParams.get("session_id");
  if (!sessionId) {
    throw new Error("Test editor authority has no session.");
  }
  source.searchParams.set("session_id", sessionId);
  source.hash = "";
  return source;
};

const activationRequest = (
  bootstrap: (url: URL) => Promise<Response> | Response,
): ReturnType<typeof vi.fn> =>
  vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const source = input instanceof Request ? input.url : String(input);
    const url = new URL(source, globalThis.location.href);
    if (url.pathname.endsWith("/_marimo-studio/bootstrap")) {
      return bootstrap(url);
    }
    if (url.pathname.endsWith("/_marimo-studio/views")) {
      return Response.json(viewList(["dashboard"]));
    }
    if (url.pathname.endsWith("/views/dashboard/project")) {
      return Response.json(sourceProject);
    }
    if (url.pathname.endsWith("/views/dashboard/source/index.html")) {
      return new Response("<main>Dashboard</main>", {
        headers: { ETag: '"revision"' },
      });
    }
    if (init?.method === "POST" && url.pathname.endsWith("/activations/7/ack")) {
      return Response.json({ schema: 1, outcome: "applied" });
    }
    throw new Error(`Unexpected request ${init?.method ?? "GET"} ${url}`);
  });

it("retries first-view authoring options after a transient inventory failure", async () => {
  vi.stubGlobal("EventSource", EventSourceStub);
  let inventories = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const source = input instanceof Request ? input.url : String(input);
      const url = new URL(source, globalThis.location.href);
      if (url.pathname.endsWith("/_marimo-studio/views")) {
        inventories += 1;
        return inventories === 1
          ? Response.json(
              { error: "temporary", message: "Authoring options are temporarily unavailable." },
              { status: 503 },
            )
          : Response.json(viewList([], "dashboard", [starter]));
      }
      throw new Error(`Unexpected request ${url}`);
    }),
  );
  const frameHost = document.createElement("div");
  const editorFrame = document.createElement("iframe");
  frameHost.append(editorFrame);
  document.body.append(frameHost);
  const user = userEvent.setup();

  render(
    <StudioHost
      host={host}
      editorFrame={editorFrame}
      publishBootstrap={vi.fn()}
      brand={{ marks: { dark: "dark.svg", light: "light.svg" } }}
    />,
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Authoring options are temporarily unavailable.",
  );
  expect(screen.getByRole("button", { name: "Create dashboard" })).toBeDisabled();
  expect(editorFrame).toHaveAttribute("inert");
  expect(editorFrame).toHaveAttribute("aria-hidden", "true");
  expect(screen.getByRole("main")).toHaveFocus();
  await user.click(screen.getByRole("button", { name: "Retry authoring options" }));

  expect(await screen.findByRole("combobox", { name: "Starter" })).toHaveValue(
    "marimo-studio/vanilla:default",
  );
  expect(screen.getByRole("button", { name: "Create dashboard" })).toBeEnabled();
  expect(inventories).toBe(2);
  expect(editorFrame.parentElement).toBe(frameHost);
  frameHost.remove();
});

it("shows first-view starter documents and unavailable recovery", async () => {
  vi.stubGlobal("EventSource", EventSourceStub);
  const unavailable = {
    ...componentStarter,
    documents: ["src/App.tsx", "src/theme.css"],
    availability: {
      available: false,
      version: null,
      reason: "Deno is unavailable.",
      action: "Install Deno to use React.",
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json(viewList([], "dashboard", [unavailable], unavailable.id))),
  );
  const editorFrame = document.createElement("iframe");

  render(
    <StudioHost
      host={host}
      editorFrame={editorFrame}
      publishBootstrap={vi.fn()}
      brand={{ marks: { dark: "dark.svg", light: "light.svg" } }}
    />,
  );

  expect(await screen.findByLabelText("Starter details")).toHaveTextContent(
    "Starts with src/App.tsx, src/theme.css",
  );
  expect(screen.getByLabelText("Starter details")).toHaveTextContent("Install Deno to use React.");
  expect(screen.getByRole("button", { name: "Create dashboard" })).toBeDisabled();
});

it("opens an already-created first view after a bootstrap retry", async () => {
  vi.stubGlobal("EventSource", EventSourceStub);
  const publicHost = {
    ...host,
    urls: { ...host.urls, bootstrap: `${host.urls.bootstrap}?region=eu` },
  };
  const configured = {
    ...ready,
    urls: {
      ...ready.urls,
      editor: "configured-editor/?file=analysis.py&marimo_studio_editor=configured&region=eu",
    },
  };
  let creates = 0;
  let createdStarter = "";
  let bootstraps = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const source = input instanceof Request ? input.url : String(input);
      const url = new URL(source, globalThis.location.href);
      if (!init?.method && url.pathname.endsWith("/_marimo-studio/views")) {
        return Response.json(viewList([], "dashboard", [componentStarter, starter]));
      }
      if (init?.method === "POST" && url.pathname.endsWith("/_marimo-studio/views")) {
        creates += 1;
        const body = createViewBodySchema.parse(await new Request(url, init).json());
        createdStarter = body.starter;
        return Response.json(
          {
            schema: 2,
            name: "dashboard",
          },
          { status: 201 },
        );
      }
      if (url.pathname.endsWith("/_marimo-studio/bootstrap")) {
        bootstraps += 1;
        return bootstraps === 1
          ? Response.json(
              { error: "temporary", message: "Bootstrap is temporarily unavailable." },
              { status: 503 },
            )
          : Response.json(configured);
      }
      if (url.pathname.includes("/source/")) {
        return new Response("", { headers: { ETag: '"revision"' } });
      }
      throw new Error(`Unexpected request ${url}`);
    }),
  );
  const frameHost = document.createElement("div");
  const editorFrame = document.createElement("iframe");
  globalThis.history.replaceState({}, "", "/entry/?region=eu");
  editorFrame.src = "editor/?file=analysis.py";
  frameHost.append(editorFrame);
  document.body.append(frameHost);
  const lazyEditorUrl = editorFrame.src;
  const configuredEditorUrl = new URL(configured.urls.editor, globalThis.location.href).href;
  const reload = vi.spyOn(editorFrame, "src", "set");
  const publishBootstrap = vi.fn();
  const user = userEvent.setup();

  render(
    <StudioHost
      host={publicHost}
      editorFrame={editorFrame}
      publishBootstrap={publishBootstrap}
      brand={{ marks: { dark: "dark.svg", light: "light.svg" } }}
    />,
  );
  expect(await screen.findByRole("combobox", { name: "Starter" })).toHaveValue(
    "marimo-studio/vanilla:default",
  );
  await user.click(await screen.findByRole("button", { name: "Create dashboard" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Bootstrap is temporarily unavailable.",
  );
  await user.click(screen.getByRole("button", { name: "Open dashboard" }));
  await vi.waitFor(() => expect(publishBootstrap).toHaveBeenCalledWith(configured));
  expect(reload).toHaveBeenCalledWith(configuredEditorUrl);
  expect(publishBootstrap.mock.invocationCallOrder[0]).toBeLessThan(
    reload.mock.invocationCallOrder[0]!,
  );
  expect(screen.queryByLabelText("Studio workspace")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Create the first view" })).toBeVisible();

  fireEvent.load(editorFrame);
  expect(await screen.findByLabelText("Studio workspace")).toBeVisible();

  expect(creates).toBe(1);
  expect(createdStarter).toBe("marimo-studio/vanilla:default");
  expect(bootstraps).toBe(2);
  expect(editorFrame).not.toHaveAttribute("inert");
  expect(editorFrame).not.toHaveAttribute("aria-hidden");
  expect(editorFrame.parentElement).toBe(frameHost);
  expect(editorFrame.src).toBe(configuredEditorUrl);
  expect(editorFrame.src).not.toBe(lazyEditorUrl);
  expect(new URL(globalThis.location.href).searchParams.get("region")).toBe("eu");
  frameHost.remove();
});

it("preserves an active editor and its public query during first-view activation", async () => {
  useActivationEvents();
  const configured = {
    ...ready,
    urls: {
      ...ready.urls,
      editor:
        "editor/?session_id=s_editor1&region=eu&marimo_studio_server=server-instance&file=analysis.py&marimo_studio_editor=editor-capability&marimo_studio_client=browser-client-1234",
    },
  };
  const bootstrapQueries: string[] = [];
  const request = activationRequest((url) => {
    bootstrapQueries.push(url.search);
    return Response.json(configured);
  });
  vi.stubGlobal("fetch", request);
  globalThis.history.replaceState({}, "", "/entry/");
  const { editorFrame, editorWindow } = mountActiveEditor("region=eu", "#scrollTo=cell-1");
  const liveEditorUrl = editorWindow.location.href;
  const replaceEditorHistory = vi.spyOn(editorWindow.history, "replaceState");
  const reload = vi.spyOn(editorFrame, "src", "set");
  const publishBootstrap = vi.fn();

  render(
    <StudioHost
      host={activationHost}
      editorFrame={editorFrame}
      publishBootstrap={publishBootstrap}
      brand={{ marks: { dark: "dark.svg", light: "light.svg" } }}
    />,
  );
  await activateFirstView();

  await vi.waitFor(() => expect(publishBootstrap).toHaveBeenCalledWith(configured));
  expect(new URLSearchParams(bootstrapQueries[0]).get("region")).toBe("eu");
  expect(new URL(globalThis.location.href).searchParams.get("region")).toBe("eu");
  expect(reload).not.toHaveBeenCalled();
  expect(replaceEditorHistory).not.toHaveBeenCalled();
  expect(editorWindow.location.href).toBe(liveEditorUrl);
  expect(new URL(editorWindow.location.href).searchParams.has("session_id")).toBe(false);
  expect(await screen.findByLabelText("Studio workspace")).toBeVisible();
  await vi.waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      expect.stringContaining("/activations/7/ack"),
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(editorFrame.isConnected).toBe(true);
  editorFrame.remove();
});

it("retries first-view activation when the editor query changes during bootstrap", async () => {
  useActivationEvents();
  globalThis.history.replaceState({}, "", "/entry/");
  const { editorFrame, editorWindow } = mountActiveEditor("region=eu&tag=a&tag=b");
  const firstBootstrap = deferred<Response>();
  const bootstrapQueries: string[] = [];
  const initialEditor = configuredEditorUrl(editorFrame, editorWindow);
  let currentBootstrap: StudioBootstrap | undefined;
  const request = activationRequest((url) => {
    bootstrapQueries.push(url.search);
    if (bootstrapQueries.length === 1) {
      return firstBootstrap.promise;
    }
    const configuredEditor = configuredEditorUrl(editorFrame, editorWindow);
    currentBootstrap = {
      ...ready,
      urls: { ...ready.urls, editor: configuredEditor.href },
    };
    return Response.json(currentBootstrap);
  });
  vi.stubGlobal("fetch", request);
  const publishBootstrap = vi.fn();

  render(
    <StudioHost
      host={activationHost}
      editorFrame={editorFrame}
      publishBootstrap={publishBootstrap}
      brand={{ marks: { dark: "dark.svg", light: "light.svg" } }}
    />,
  );
  await activateFirstView();
  await vi.waitFor(() => expect(bootstrapQueries).toHaveLength(1));
  const updatedEditor = new URL(editorWindow.location.href);
  updatedEditor.searchParams.delete("tag");
  updatedEditor.searchParams.append("tag", "b");
  updatedEditor.searchParams.append("tag", "a");
  editorWindow.history.replaceState(
    editorWindow.history.state,
    "",
    `${updatedEditor.pathname}${updatedEditor.search}${updatedEditor.hash}`,
  );
  firstBootstrap.resolve(
    Response.json({
      ...ready,
      urls: { ...ready.urls, editor: initialEditor.href },
    }),
  );

  await vi.waitFor(() => expect(bootstrapQueries).toHaveLength(2));
  await vi.waitFor(() => expect(publishBootstrap).toHaveBeenCalledWith(currentBootstrap));
  expect(new URLSearchParams(bootstrapQueries[0]).getAll("tag")).toEqual(["a", "b"]);
  expect(new URLSearchParams(bootstrapQueries[1]).getAll("tag")).toEqual(["b", "a"]);
  expect(new URL(globalThis.location.href).searchParams.getAll("tag")).toEqual(["b", "a"]);
  expect(new URL(editorWindow.location.href).searchParams.getAll("tag")).toEqual(["b", "a"]);
  await vi.waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      expect.stringContaining("/activations/7/ack"),
      expect.objectContaining({ method: "POST" }),
    ),
  );
  editorFrame.remove();
});

it.each(["document", "binding authority"] as const)(
  "rejects retained editor %s changes during bootstrap",
  async (change) => {
    useActivationEvents();
    globalThis.history.replaceState({}, "", "/entry/");
    const { editorFrame, editorWindow } = mountActiveEditor("region=eu");
    const bootstrap = deferred<Response>();
    const request = activationRequest(() => bootstrap.promise);
    vi.stubGlobal("fetch", request);
    const publishBootstrap = vi.fn();

    const rendered = render(
      <StudioHost
        host={activationHost}
        editorFrame={editorFrame}
        publishBootstrap={publishBootstrap}
        brand={{ marks: { dark: "dark.svg", light: "light.svg" } }}
      />,
    );
    await activateFirstView();
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    if (change === "document") {
      vi.spyOn(editorFrame, "contentDocument", "get").mockReturnValue(
        document.implementation.createHTMLDocument(),
      );
    } else {
      const changedEditor = new URL(editorWindow.location.href);
      changedEditor.searchParams.set("marimo_studio_editor", "foreign-capability");
      editorWindow.history.replaceState(
        editorWindow.history.state,
        "",
        `${changedEditor.pathname}${changedEditor.search}`,
      );
    }
    bootstrap.resolve(
      Response.json({
        ...ready,
        urls: { ...ready.urls, editor: configuredEditorUrl(editorFrame, editorWindow).href },
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The active Marimo editor changed while Studio opened.",
    );
    expect(publishBootstrap).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Studio workspace")).not.toBeInTheDocument();
    expect(request).toHaveBeenCalledTimes(1);
    rendered.unmount();
    editorFrame.remove();
  },
);

it("fails closed when the editor query outlives the bounded bootstrap retries", async () => {
  useActivationEvents();
  globalThis.history.replaceState({}, "", "/entry/");
  const { editorFrame, editorWindow } = mountActiveEditor("tag=a&tag=b");
  let attempts = 0;
  const request = activationRequest(() => {
    attempts += 1;
    const configuredEditor = configuredEditorUrl(editorFrame, editorWindow);
    const changedEditor = new URL(editorWindow.location.href);
    changedEditor.searchParams.delete("tag");
    for (const value of attempts % 2 === 0 ? ["a", "b"] : ["b", "a"]) {
      changedEditor.searchParams.append("tag", value);
    }
    editorWindow.history.replaceState(
      editorWindow.history.state,
      "",
      `${changedEditor.pathname}${changedEditor.search}`,
    );
    return Response.json({
      ...ready,
      urls: { ...ready.urls, editor: configuredEditor.href },
    });
  });
  vi.stubGlobal("fetch", request);
  const publishBootstrap = vi.fn();

  const rendered = render(
    <StudioHost
      host={activationHost}
      editorFrame={editorFrame}
      publishBootstrap={publishBootstrap}
      brand={{ marks: { dark: "dark.svg", light: "light.svg" } }}
    />,
  );
  await activateFirstView();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The Marimo editor query kept changing while Studio opened.",
  );
  expect(attempts).toBeGreaterThan(1);
  const terminalAttempts = attempts;
  await act(async () => Promise.resolve());
  expect(attempts).toBe(terminalAttempts);
  expect(publishBootstrap).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("Studio workspace")).not.toBeInTheDocument();
  rendered.unmount();
  editorFrame.remove();
});

it.each([
  ["notebook", "file", "foreign.py"],
  ["client", "marimo_studio_client", "foreign-client"],
  ["server", "marimo_studio_server", "foreign-server"],
  ["session", "session_id", "s_foreign1"],
  ["binding capability", "marimo_studio_editor", "foreign-capability"],
  ["public query", "region", "us"],
] as const)("rejects a configured editor with mismatched %s", async (_label, key, value) => {
  useActivationEvents();
  globalThis.history.replaceState({}, "", "/entry/");
  const { editorFrame } = mountActiveEditor("region=eu");
  const configuredEditor = new URL(editorFrame.src);
  configuredEditor.searchParams.set(key, value);
  const configured = {
    ...ready,
    urls: { ...ready.urls, editor: configuredEditor.href },
  };
  const request = activationRequest(() => Response.json(configured));
  vi.stubGlobal("fetch", request);
  const publishBootstrap = vi.fn();

  const rendered = render(
    <StudioHost
      host={activationHost}
      editorFrame={editorFrame}
      publishBootstrap={publishBootstrap}
      brand={{ marks: { dark: "dark.svg", light: "light.svg" } }}
    />,
  );
  await activateFirstView();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The configured Marimo editor does not match the active editor.",
  );
  expect(publishBootstrap).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("Studio workspace")).not.toBeInTheDocument();
  expect(request).toHaveBeenCalledTimes(1);
  rendered.unmount();
  editorFrame.remove();
});
