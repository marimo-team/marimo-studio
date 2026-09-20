import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";
import type { StudioHostBootstrap } from "@marimo-studio/protocol/studio-host";

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vite-plus/test";
import { z } from "zod";

import { StudioHost } from "../src/app/StudioHost.tsx";
import { PreviewDeck } from "../src/features/preview/deck.ts";
import {
  starter,
  componentStarter,
  unbuiltView,
  viewGeneration,
  viewList,
  viewOwner,
} from "./fixtures.ts";
import { deferred } from "./studio-test-support.ts";

const host: StudioHostBootstrap = {
  schema: 1,
  state: "needs-view",
  defaultView: "dashboard",
  generation: viewGeneration(0),
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
  defaultView: "dashboard",
  selectedView: "dashboard",
  views: ["dashboard"],
  runtimes: [{ id: "server", label: "Python" }],
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

const createViewBodySchema = z
  .object({
    catalog_generation: z.string(),
    name: z.string(),
    starter: z.string(),
  })
  .strict();

const viewGenerationConflictResponse = () =>
  Response.json(
    {
      error: "view-generation-conflict",
      message: "The view catalog changed before this view was created.",
      hint: "Retry with the current view choices.",
      transient: true,
    },
    { status: 409 },
  );

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
  ...viewOwner,
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
  return { editorFrame, editorWindow };
};

const configuredEditorUrl = (editorWindow: Window): URL => {
  const source = new URL(editorWindow.location.href);
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
  await user.click(screen.getByText("Add view", { exact: true }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Authoring options are temporarily unavailable.",
  );
  expect(screen.getByRole("button", { name: "Create view" })).toBeDisabled();
  expect(editorFrame).not.toHaveAttribute("inert");
  expect(editorFrame).not.toHaveAttribute("aria-hidden");
  expect(screen.getByRole("textbox", { name: "New view" })).toHaveFocus();
  await user.click(screen.getByRole("button", { name: "Retry view choices" }));

  expect(await screen.findByRole("radio", { name: new RegExp(starter.title) })).toBeChecked();
  expect(screen.getByRole("button", { name: "Create view" })).toBeEnabled();
  expect(inventories).toBe(2);
  expect(editorFrame.parentElement).toBe(frameHost);
  editorFrame.remove();
});

it("refreshes first-view ownership after a create conflict", async () => {
  vi.stubGlobal("EventSource", EventSourceStub);
  const initialGeneration = viewGeneration(10);
  const replacementGeneration = viewGeneration(11);
  const catalogGenerations = [initialGeneration, replacementGeneration, replacementGeneration];
  const submittedGenerations: string[] = [];
  let inventories = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const source = input instanceof Request ? input.url : String(input);
      const url = new URL(source, globalThis.location.href);
      if (!init?.method && url.pathname.endsWith("/_marimo-studio/views")) {
        const generation = catalogGenerations[inventories] ?? replacementGeneration;
        inventories += 1;
        return Response.json({
          ...viewList([], "dashboard", [starter]),
          generation,
        });
      }
      if (init?.method === "POST" && url.pathname.endsWith("/_marimo-studio/views")) {
        const body = createViewBodySchema.parse(await new Request(url, init).json());
        submittedGenerations.push(body.catalog_generation);
        return viewGenerationConflictResponse();
      }
      throw new Error(`Unexpected request ${init?.method ?? "GET"} ${url}`);
    }),
  );
  const editorFrame = document.createElement("iframe");
  const user = userEvent.setup();

  render(
    <StudioHost
      host={{ ...host, generation: viewGeneration(9) }}
      editorFrame={editorFrame}
      publishBootstrap={vi.fn()}
      brand={{ marks: { dark: "dark.svg", light: "light.svg" } }}
    />,
  );
  await user.click(screen.getByText("Add view", { exact: true }));

  await user.click(await screen.findByRole("button", { name: "Create view" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The view catalog changed before this view was created.",
  );
  expect(inventories).toBe(2);

  await user.click(screen.getByRole("button", { name: "Create view" }));
  await vi.waitFor(() => expect(submittedGenerations).toHaveLength(2));

  expect(submittedGenerations).toEqual([initialGeneration, replacementGeneration]);
  expect(inventories).toBe(3);
});

it("replaces an in-flight catalog retry after a create conflict", async () => {
  vi.stubGlobal("EventSource", EventSourceStub);
  const initialGeneration = viewGeneration(20);
  const staleGeneration = viewGeneration(21);
  const currentGeneration = viewGeneration(22);
  const retryInventory = deferred<Response>();
  const submittedGenerations: string[] = [];
  let inventories = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const source = input instanceof Request ? input.url : String(input);
      const url = new URL(source, globalThis.location.href);
      if (!init?.method && url.pathname.endsWith("/_marimo-studio/views")) {
        inventories += 1;
        if (inventories === 1) {
          return Response.json({
            ...viewList([], "dashboard", [starter]),
            generation: initialGeneration,
          });
        }
        if (inventories === 2) {
          return Response.json(
            { error: "temporary", message: "Authoring options are temporarily unavailable." },
            { status: 503 },
          );
        }
        if (inventories === 3) {
          return retryInventory.promise;
        }
        return Response.json({
          ...viewList([], "dashboard", [starter]),
          generation: currentGeneration,
        });
      }
      if (init?.method === "POST" && url.pathname.endsWith("/_marimo-studio/views")) {
        const body = createViewBodySchema.parse(await new Request(url, init).json());
        submittedGenerations.push(body.catalog_generation);
        return viewGenerationConflictResponse();
      }
      throw new Error(`Unexpected request ${init?.method ?? "GET"} ${url}`);
    }),
  );
  const editorFrame = document.createElement("iframe");
  const user = userEvent.setup();

  render(
    <StudioHost
      host={{ ...host, generation: viewGeneration(19) }}
      editorFrame={editorFrame}
      publishBootstrap={vi.fn()}
      brand={{ marks: { dark: "dark.svg", light: "light.svg" } }}
    />,
  );
  await user.click(screen.getByText("Add view", { exact: true }));

  await user.click(await screen.findByRole("button", { name: "Create view" }));
  await user.click(await screen.findByRole("button", { name: "Retry view choices" }));
  await vi.waitFor(() => expect(inventories).toBe(3));

  await user.click(screen.getByRole("button", { name: "Create view" }));
  await vi.waitFor(() => expect(submittedGenerations).toHaveLength(2));
  await vi.waitFor(() => expect(inventories).toBe(4));
  retryInventory.resolve(
    Response.json({
      ...viewList([], "dashboard", [starter]),
      generation: staleGeneration,
    }),
  );

  await user.click(await screen.findByRole("button", { name: "Create view" }));
  await vi.waitFor(() => expect(submittedGenerations).toHaveLength(3));

  expect(submittedGenerations).toEqual([initialGeneration, initialGeneration, currentGeneration]);
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

  await userEvent.click(screen.getByText("Add view", { exact: true }));
  expect(await screen.findByText("Install Deno to use React.")).toBeVisible();
  expect(screen.getByRole("radio")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Create view" })).toBeDisabled();
});

it("opens an already-created first view after a bootstrap retry", async () => {
  vi.stubGlobal("EventSource", EventSourceStub);
  const { editorFrame, editorWindow } = mountActiveEditor("?region=eu");
  const publicHost = { ...host, urls: { ...host.urls, editor: editorFrame.src } };
  const configured = {
    ...ready,
    urls: { ...ready.urls, editor: configuredEditorUrl(editorWindow).href },
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
        expect(body.catalog_generation).toBe(host.generation);
        expect(body.name).toBe("dashboard");
        createdStarter = body.starter;
        return Response.json(
          {
            schema: 1,
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
  const frameHost = editorFrame.parentElement!;
  const retainedEditorUrl = editorFrame.src;
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
  await user.click(screen.getByText("Add view", { exact: true }));
  expect(await screen.findByRole("radio", { name: new RegExp(starter.title) })).toBeChecked();
  await user.click(await screen.findByRole("button", { name: "Create view" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Bootstrap is temporarily unavailable.",
  );
  await user.click(screen.getByRole("button", { name: "Open dashboard" }));
  await vi.waitFor(() => expect(publishBootstrap).toHaveBeenCalledWith(configured));
  expect(reload).not.toHaveBeenCalled();
  expect(await screen.findByLabelText("Studio workspace")).toBeVisible();
  await user.click(screen.getByLabelText("Python preview runtime"));
  expect(screen.getByRole("status", { name: "Preview runtime status" })).toBeVisible();

  expect(creates).toBe(1);
  expect(createdStarter).toBe("marimo-studio/vanilla:default");
  expect(bootstraps).toBe(2);
  expect(editorFrame).not.toHaveAttribute("inert");
  expect(editorFrame).not.toHaveAttribute("aria-hidden");
  expect(editorFrame.parentElement).toBe(frameHost);
  expect(editorFrame.src).toBe(retainedEditorUrl);
  expect(new URL(globalThis.location.href).searchParams.get("region")).toBe("eu");
  editorFrame.remove();
});

it("preserves an active editor and its public query during first-view activation", async () => {
  useActivationEvents();
  const documentAttached = deferred<boolean>();
  const stageNavigation = vi.spyOn(PreviewDeck.prototype, "stageNavigation").mockReturnValue({
    ready: documentAttached.promise,
    rollback: async () => undefined,
  });
  const automationTarget = vi.spyOn(PreviewDeck.prototype, "automationTarget").mockReturnValue({
    previewUrl: "http://localhost:3000/dashboard/",
    frameSelector: 'iframe[data-preview-view-frame="dashboard"]',
  });
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
  expect(new URL(editorWindow.location.href).searchParams.has("session_id")).toBe(true);
  expect(await screen.findByLabelText("Studio workspace")).toBeVisible();
  await vi.waitFor(() =>
    expect(stageNavigation).toHaveBeenCalledWith(
      "dashboard",
      false,
      undefined,
      expect.any(AbortSignal),
      "document",
    ),
  );
  expect(
    request.mock.calls.some(([input]) =>
      String(input instanceof Request ? input.url : input).includes("/activations/7/ack"),
    ),
  ).toBe(false);
  expect(automationTarget).not.toHaveBeenCalled();
  await act(async () => documentAttached.resolve(true));
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
  const documentAttached = deferred<boolean>();
  const stageNavigation = vi.spyOn(PreviewDeck.prototype, "stageNavigation").mockReturnValue({
    ready: documentAttached.promise,
    rollback: async () => undefined,
  });
  const automationTarget = vi.spyOn(PreviewDeck.prototype, "automationTarget").mockReturnValue({
    previewUrl: "http://localhost:3000/dashboard/",
    frameSelector: 'iframe[data-preview-view-frame="dashboard"]',
  });
  globalThis.history.replaceState({}, "", "/entry/");
  const { editorFrame, editorWindow } = mountActiveEditor("region=eu&tag=a&tag=b");
  const firstBootstrap = deferred<Response>();
  const bootstrapQueries: string[] = [];
  const initialEditor = configuredEditorUrl(editorWindow);
  let currentBootstrap: StudioBootstrap | undefined;
  const request = activationRequest((url) => {
    bootstrapQueries.push(url.search);
    if (bootstrapQueries.length === 1) {
      return firstBootstrap.promise;
    }
    const configuredEditor = configuredEditorUrl(editorWindow);
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
    expect(stageNavigation).toHaveBeenCalledWith(
      "dashboard",
      false,
      undefined,
      expect.any(AbortSignal),
      "document",
    ),
  );
  expect(
    request.mock.calls.some(([input]) =>
      String(input instanceof Request ? input.url : input).includes("/activations/7/ack"),
    ),
  ).toBe(false);
  expect(automationTarget).not.toHaveBeenCalled();
  await act(async () => documentAttached.resolve(true));
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
        urls: { ...ready.urls, editor: configuredEditorUrl(editorWindow).href },
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
    const configuredEditor = configuredEditorUrl(editorWindow);
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
