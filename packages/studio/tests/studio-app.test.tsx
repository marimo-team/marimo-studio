import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vite-plus/test";

import type { ViewRemote } from "../src/features/views/remote.ts";

import { createStudioServices } from "../src/app/services.ts";
import { StudioErrorBoundary } from "../src/app/StudioErrorBoundary.tsx";
import { RuntimeStatus } from "../src/features/navigation/RuntimeStatus.tsx";
import { Toolbar } from "../src/features/navigation/Toolbar.tsx";
import { PreviewDeck } from "../src/features/preview/deck.ts";
import { previewStatus } from "../src/features/preview/status.ts";
import { ViewController } from "../src/features/views/controller.ts";
import { LayoutController } from "../src/features/workspace/controller.ts";
import { Divider } from "../src/features/workspace/Divider.tsx";
import { computeLayout, defaultWorkspaceLayout } from "../src/features/workspace/model.ts";
import { starter, unbuiltView, viewList } from "./fixtures.ts";
import { deferred, studioBootstrap as bootstrap } from "./studio-test-support.ts";

const brand = {
  marks: {
    dark: "dark-mark.svg",
    light: "light-mark.svg",
  },
};

const sourceProject = (view: string) => ({
  schema: 1 as const,
  view,
  provider: "test/source",
  provider_options: {},
  documents: [{ path: "src/App.tsx", language: "typescriptreact", access: "edit" }],
  mounts: [],
  diagnostics: [],
  build: unbuiltView,
  artifact: null,
});

const remote = (starters = [starter], defaultStarter = starter.id): ViewRemote => {
  let views = ["dashboard", "report"];
  return {
    list: vi.fn(async () => viewList(views, views[0], starters, defaultStarter)),
    create: vi.fn(async (name: string, _starter: string) => {
      views = [...views, name].sort();
      return {
        schema: 2 as const,
        name,
        provider: "marimo-studio/vanilla",
        studio_url: `/studio/${name}/`,
        view_url: `/${name}/`,
      };
    }),
    remove: vi.fn(async (name: string) => {
      views = views.filter((view) => view !== name);
      return { ...viewList(views, views[0], starters, defaultStarter), name };
    }),
  };
};

const controllers = (starters = [starter], defaultStarter = starter.id) => {
  const layout = new LayoutController("test-workspace", bootstrap.selectedView);
  const preview = new PreviewDeck({
    initialView: bootstrap.selectedView,
    initialRuntime: bootstrap.defaultRuntime,
    initialNavigation: { query: "", hash: "" },
    runtimes: bootstrap.runtimes.map((runtime) => runtime.id),
    viewUrl: (view, runtime) => `/${view}/?runtime=${runtime}`,
    supportUrl: (view) => `/_marimo-studio/views/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  const views = new ViewController(
    bootstrap.selectedView,
    [...bootstrap.views],
    remote(starters, defaultStarter),
    vi.fn(async () => true),
    vi.fn(async () => true),
    vi.fn(),
    starters,
    defaultStarter,
  );
  return { layout, preview, views };
};

describe("Studio shell", () => {
  it("explains a degraded runtime with its diagnostic", () => {
    render(
      <RuntimeStatus
        status={previewStatus("server", {
          phase: "degraded",
          diagnostics: [
            {
              code: "value-stale",
              severity: "warning",
              message: "The projected value is stale.",
              hint: "Wait for the notebook to finish running.",
              view: "dashboard",
              scope: "projection",
              projection: "value",
              target: "summary.total",
            },
          ],
        })}
      />,
    );

    const status = screen.getByTitle(
      "The projected value is stale. Wait for the notebook to finish running.",
    );
    expect(status).toHaveTextContent("Live with 1 warning");
  });

  it("restores persisted layout trees from the current application namespace", () => {
    const storagePrefix = `marimo-studio:workspace-layout:v3:${bootstrap.workspaceId}`;
    const persisted = {
      schema: 2,
      mode: "workspace",
      source: { type: "pane", id: "pane-source", surface: "source" },
      workspace: {
        type: "split",
        id: "saved-workspace",
        axis: "x",
        ratio: 0.4,
        first: { type: "pane", id: "pane-notebook", surface: "notebook" },
        second: { type: "pane", id: "pane-preview", surface: "preview" },
      },
      compact: "preview",
    };
    globalThis.localStorage.setItem(
      `${storagePrefix}:${bootstrap.selectedView}`,
      JSON.stringify(persisted),
    );
    const services = createStudioServices(bootstrap);
    const serverPreviewUrl = new URL(services.preview.getSnapshot().states.server.url);

    expect(services.layout.getSnapshot().source).toEqual(persisted.source);
    expect(services.layout.getSnapshot().workspace).toEqual(persisted.workspace);
    expect(serverPreviewUrl.searchParams.get("marimo_studio_client")).toBe(bootstrap.clientId);
    expect(serverPreviewUrl.searchParams.get("marimo_studio_server")).toBe(
      bootstrap.serverInstance,
    );
    services.dispose();
  });

  it("commits authored navigation after the current source is saved", async () => {
    const services = createStudioServices(bootstrap);
    vi.spyOn(services.source, "prepareViewChange").mockResolvedValue(true);
    const selectSource = vi.spyOn(services.source, "selectView");
    const synchronize = vi
      .spyOn(services.preview, "synchronizeNavigationQuery")
      .mockResolvedValue(true);
    const stageView = vi.spyOn(services.preview, "stageView").mockReturnValue({
      ready: Promise.resolve(true),
      rollback: vi.fn(async () => {}),
    });
    const navigation = { query: "?region=apac", hash: "#app-shell" };

    expect(await services.views.choose("report", "preserve", navigation)).toBe(true);
    expect(synchronize).toHaveBeenCalledOnce();
    expect(synchronize).toHaveBeenCalledWith("?region=apac");
    expect(stageView).toHaveBeenCalledWith("report", navigation);
    expect(selectSource).toHaveBeenCalledWith("report");
    expect(globalThis.location.search).toContain("region=apac");
    expect(globalThis.location.hash).toBe("#app-shell");
    services.dispose();
  });

  it("switches the preview while incoming source inspection is pending", async () => {
    const reportProject = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(
          input instanceof Request ? input.url : String(input),
          globalThis.location.href,
        );
        if (url.pathname.endsWith("/dashboard/project")) {
          return Response.json(sourceProject("dashboard"));
        }
        if (url.pathname.endsWith("/dashboard/source/src/App.tsx")) {
          return new Response("source:dashboard", { headers: { ETag: '"revision:dashboard"' } });
        }
        if (url.pathname.endsWith("/report/project")) {
          return await reportProject.promise;
        }
        if (url.pathname.endsWith("/report/source/src/App.tsx")) {
          return new Response("source:report", { headers: { ETag: '"revision:report"' } });
        }
        throw new Error(`Unexpected Source request ${url}`);
      }),
    );
    const services = createStudioServices(bootstrap);
    await services.source.start();
    services.layout.selectMode("preview");
    const stageView = vi.spyOn(services.preview, "stageView").mockReturnValue({
      ready: Promise.resolve(true),
      rollback: vi.fn(async () => {}),
    });

    expect(await services.views.choose("report")).toBe(true);

    expect(stageView).toHaveBeenCalledWith("report", undefined);
    expect(services.views.getSnapshot().current).toBe("report");
    expect(services.layout.getSnapshot().mode).toBe("preview");
    expect(services.source.getSnapshot()).toMatchObject({
      view: "report",
      active: null,
      documents: [],
    });
    reportProject.resolve(Response.json(sourceProject("report")));
    await vi.waitFor(() =>
      expect(services.source.getSnapshot()).toMatchObject({
        view: "report",
        active: "src/App.tsx",
        documents: [{ path: "src/App.tsx", loaded: true }],
      }),
    );
    services.dispose();
  });

  it("keeps the selected view active when incoming source inspection fails", async () => {
    globalThis.history.replaceState({}, "", "/studio/dashboard/?region=emea#current-section");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(input instanceof Request ? input.url : String(input), location.href);
        if (url.pathname.endsWith("/dashboard/project")) {
          return Response.json(sourceProject("dashboard"));
        }
        if (url.pathname.endsWith("/dashboard/source/src/App.tsx")) {
          return new Response("source:dashboard", { headers: { ETag: '"revision:dashboard"' } });
        }
        if (url.pathname.endsWith("/report/project")) {
          return Response.json({ message: "inspection failed" }, { status: 500 });
        }
        throw new Error(`Unexpected Source request ${url}`);
      }),
    );
    const services = createStudioServices(bootstrap);
    await services.source.start();
    vi.spyOn(services.preview, "synchronizeNavigationQuery").mockResolvedValue(true);
    const stageView = vi.spyOn(services.preview, "stageView").mockReturnValue({
      ready: Promise.resolve(true),
      rollback: vi.fn(async () => {}),
    });

    expect(
      await services.views.choose("report", "preserve", {
        query: "?region=apac",
        hash: "#target-section",
      }),
    ).toBe(true);
    expect(services.views.getSnapshot().current).toBe("report");
    expect(stageView).toHaveBeenCalledOnce();
    expect(globalThis.location.pathname).toBe("/studio/report/");
    await vi.waitFor(() =>
      expect(services.source.getSnapshot()).toMatchObject({
        view: "report",
        documents: [],
        targetDiagnostic: { view: "report" },
      }),
    );
    services.dispose();
  });

  it("keeps menu, preview, route, and real Source on the current view when query preparation fails", async () => {
    globalThis.history.replaceState({}, "", "/studio/dashboard/?region=emea#current-section");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const source = input instanceof Request ? input.url : String(input);
        const url = new URL(source, globalThis.location.href);
        const match =
          /\/_marimo-studio\/views\/(dashboard|report)\/(project|source\/src\/App\.tsx)$/.exec(
            url.pathname,
          );
        if (!match) {
          throw new Error(`Unexpected Source request ${url}`);
        }
        const [, view, resource] = match;
        if (resource === "project") {
          return Response.json({
            schema: 1,
            view,
            provider: "test/source",
            provider_options: {},
            documents: [{ path: "src/App.tsx", language: "typescriptreact", access: "edit" }],
            mounts: [],
            diagnostics: [],
            build: unbuiltView,
            artifact: null,
          });
        }
        return new Response(`source:${view}`, {
          headers: { ETag: `"revision:${view}"` },
        });
      }),
    );
    const services = createStudioServices(bootstrap);
    await services.source.start();
    const sourceBefore = services.source.getSnapshot();
    const previewBefore = services.preview.getSnapshot().states.server?.url;
    const selectSource = vi.spyOn(services.source, "selectView");
    vi.spyOn(services.preview, "synchronizeNavigationQuery").mockResolvedValue(false);
    const stageView = vi.spyOn(services.preview, "stageView");

    expect(
      await services.views.choose("report", "preserve", {
        query: "?region=apac",
        hash: "#app-shell",
      }),
    ).toBe(false);
    expect(selectSource).not.toHaveBeenCalled();
    expect(stageView).not.toHaveBeenCalled();
    expect(services.views.getSnapshot().current).toBe("dashboard");
    expect(services.source.getSnapshot()).toEqual(sourceBefore);
    expect(services.preview.getSnapshot().states.server?.url).toBe(previewBefore);
    expect(globalThis.location.pathname).toBe("/studio/dashboard/");
    expect(globalThis.location.search).toContain("region=emea");
    expect(globalThis.location.hash).toBe("#current-section");
    services.dispose();
  });

  it("preserves same-view query and hash when editor synchronization rejects navigation", async () => {
    globalThis.history.replaceState({}, "", "/studio/dashboard/?region=emea#current-section");
    const services = createStudioServices(bootstrap);
    vi.spyOn(services.preview, "synchronizeNavigationQuery").mockResolvedValue(false);
    const navigate = vi.spyOn(services.preview, "navigateWithinView");

    expect(
      await services.views.choose("dashboard", "preserve", {
        query: "?region=apac",
        hash: "#target",
      }),
    ).toBe(false);

    expect(navigate).not.toHaveBeenCalled();
    expect(globalThis.location.pathname).toBe("/studio/dashboard/");
    expect(globalThis.location.search).toBe("?region=emea");
    expect(globalThis.location.hash).toBe("#current-section");
    services.dispose();
  });

  it("cancels pending view navigation before removing a non-current view", async () => {
    globalThis.history.replaceState({}, "", "/studio/dashboard/?region=emea#current-section");
    let removed = false;
    const request = vi.fn<typeof globalThis.fetch>(async (input, init) => {
      const url = new URL(
        input instanceof Request ? input.url : String(input),
        globalThis.location.href,
      );
      const method = init?.method ?? (input instanceof Request ? input.method : "GET");
      if (url.pathname === "/_marimo-studio/views") {
        return Response.json(viewList(removed ? ["dashboard"] : ["dashboard", "report"]));
      }
      if (url.pathname === "/_marimo-studio/views/report" && method === "DELETE") {
        removed = true;
        return Response.json({ ...viewList(["dashboard"]), name: "report" });
      }
      const match =
        /\/_marimo-studio\/views\/(dashboard|report)\/(project|source\/src\/App\.tsx)$/.exec(
          url.pathname,
        );
      if (!match) {
        throw new Error(`Unexpected request ${method} ${url}`);
      }
      const [, view, resource] = match;
      if (resource === "project") {
        return Response.json(sourceProject(view!));
      }
      return new Response("source:dashboard", {
        headers: { ETag: '"revision:dashboard"' },
      });
    });
    vi.stubGlobal("fetch", request);
    const services = createStudioServices(bootstrap);
    await services.views.refreshInventory();
    await services.source.start();
    const navigation = deferred<boolean>();
    const synchronize = vi
      .spyOn(services.preview, "synchronizeNavigationQuery")
      .mockReturnValue(navigation.promise);
    const before = {
      source: services.source.getSnapshot(),
      layout: services.layout.getSnapshot(),
      preview: services.preview.getSnapshot(),
      route: globalThis.location.href,
    };

    const choosing = services.views.choose("report", "build", { query: "?pending=1", hash: "" });
    await vi.waitFor(() => expect(synchronize).toHaveBeenCalledWith("?pending=1"));
    services.views.beginRemoval("report");
    expect(await services.views.deleteSelected()).toBe(true);
    navigation.resolve(true);
    expect(await choosing).toBe(false);

    expect(services.views.getSnapshot()).toMatchObject({
      current: "dashboard",
      views: ["dashboard"],
    });
    expect(services.source.getSnapshot()).toEqual(before.source);
    expect(services.layout.getSnapshot()).toEqual(before.layout);
    expect(services.preview.getSnapshot()).toEqual(before.preview);
    expect(globalThis.location.href).toBe(before.route);
    services.dispose();
  });

  it("loads authoring options without waiting for the workspace event stream", async () => {
    class EventSourceWithoutReady {
      addEventListener(): void {}
      close(): void {}
    }
    vi.stubGlobal("EventSource", EventSourceWithoutReady);
    const request = vi.fn(async () => Response.json(viewList(["dashboard", "report"])));
    vi.stubGlobal("fetch", request);
    const services = createStudioServices(bootstrap);
    vi.spyOn(services.source, "start").mockResolvedValue();
    const editor = document.createElement("iframe");
    const frames = new Map(
      bootstrap.runtimes.map((runtime) => [runtime.id, document.createElement("iframe")]),
    );

    await services.start(editor, frames);
    await vi.waitFor(() =>
      expect(services.views.getSnapshot().starterCatalog).toEqual({ phase: "ready" }),
    );

    expect(request).toHaveBeenCalledOnce();
    expect(services.views.getSnapshot().starters).toEqual([starter]);
    services.dispose();
  });

  it("reconciles the workspace stream only when an editor reload abandons a mutation", async () => {
    const eventSources: Array<{ close: () => void }> = [];
    class EventSourceStub {
      constructor() {
        eventSources.push(this);
      }
      addEventListener(): void {}
      close(): void {}
    }
    vi.stubGlobal("EventSource", EventSourceStub);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(viewList(["dashboard", "report"]))),
    );
    const services = createStudioServices(bootstrap);
    vi.spyOn(services.source, "start").mockResolvedValue();
    const reload = vi
      .spyOn(services.preview, "editorDocumentReloaded")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    const buildStarted = vi.spyOn(services.preview, "presentationBuildStarted");
    const editor = document.createElement("iframe");
    const frames = new Map(
      bootstrap.runtimes.map((runtime) => [runtime.id, document.createElement("iframe")]),
    );
    await services.start(editor, frames);
    buildStarted.mockClear();

    fireEvent.load(editor);
    expect(eventSources).toHaveLength(1);
    expect(buildStarted).not.toHaveBeenCalled();

    fireEvent.load(editor);
    expect(reload).toHaveBeenCalledTimes(2);
    expect(eventSources).toHaveLength(2);
    expect(buildStarted).toHaveBeenCalledWith("dashboard");
    services.dispose();
  });

  it("acknowledges host promotion before source hydration finishes", async () => {
    class EventSourceStub {
      addEventListener(): void {}
      close(): void {}
    }
    vi.stubGlobal("EventSource", EventSourceStub);
    const request = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", request);
    let finishSource!: () => void;
    const sourcePending = new Promise<void>((resolve) => {
      finishSource = resolve;
    });
    const services = createStudioServices(bootstrap, undefined, {
      schema: 1,
      generation: 12,
      view: "dashboard",
    });
    vi.spyOn(services.source, "start").mockReturnValue(sourcePending);
    const editor = document.createElement("iframe");
    const frames = new Map(
      bootstrap.runtimes.map((runtime) => [runtime.id, document.createElement("iframe")]),
    );

    const starting = services.start(editor, frames);
    await vi.waitFor(() =>
      expect(request).toHaveBeenCalledWith(
        expect.stringContaining("/activations/12/ack"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(services.source.start).toHaveBeenCalledOnce();

    finishSource();
    await starting;
    services.dispose();
  });

  it("keeps mode selection synchronized across primary and overflow navigation", async () => {
    const user = userEvent.setup();
    const previousLayout = new LayoutController("test-workspace", bootstrap.selectedView);
    previousLayout.selectMode("preview");
    previousLayout.dispose();
    const { layout, preview, views } = controllers();
    render(
      <Toolbar
        bootstrap={bootstrap}
        brand={brand}
        compact={false}
        compactSurfaces={["notebook", "preview"]}
        preview={preview}
        views={views}
        layout={layout}
      />,
    );

    expect(screen.getAllByRole("button", { name: "Develop" })[0]).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByLabelText("Workspace options"));
    let overflow = within(screen.getAllByRole("navigation", { name: "Studio mode" }).at(-1)!);
    expect(overflow.getByRole("button", { name: "Develop" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(overflow.getByRole("button", { name: "Source" }));

    await user.click(screen.getByLabelText("Workspace options"));
    overflow = within(screen.getAllByRole("navigation", { name: "Studio mode" }).at(-1)!);
    expect(overflow.getByRole("button", { name: "Develop" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(overflow.getByRole("button", { name: "Source" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByLabelText("Workspace options"));

    await user.click(screen.getAllByRole("button", { name: "Preview" })[0]);
    expect(screen.getAllByRole("button", { name: "Preview" })[0]).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    layout.dispose();
    preview.dispose();
    views.dispose();
  });

  it("disables both runtime menus while a view selection owns the preview", async () => {
    const user = userEvent.setup();
    const selection = deferred<boolean>();
    const layout = new LayoutController("runtime-selection", bootstrap.selectedView);
    const preview = new PreviewDeck({
      initialView: bootstrap.selectedView,
      initialRuntime: bootstrap.defaultRuntime,
      initialNavigation: { query: "", hash: "" },
      runtimes: bootstrap.runtimes.map((runtime) => runtime.id),
      viewUrl: (view, runtime) => `/${view}/?runtime=${runtime}`,
      supportUrl: (view) => `/_marimo-studio/views/${view}`,
      syncQuery: vi.fn(),
      syncEditorQuery: vi.fn(async () => "accepted" as const),
      navigate: vi.fn(),
    });
    const views = new ViewController(
      bootstrap.selectedView,
      [...bootstrap.views],
      remote(),
      vi.fn(() => selection.promise),
      vi.fn(async () => true),
      vi.fn(),
      [starter],
      starter.id,
    );
    const switchRuntime = vi.spyOn(preview, "switchRuntime");
    render(
      <Toolbar
        bootstrap={bootstrap}
        brand={brand}
        compact={false}
        compactSurfaces={["notebook", "preview"]}
        preview={preview}
        views={views}
        layout={layout}
      />,
    );

    await user.click(screen.getByLabelText("Switch view: dashboard"));
    await user.click(screen.getByRole("button", { name: "report" }));
    await vi.waitFor(() => expect(views.getSnapshot().selecting).toBe("report"));

    expect(screen.getByLabelText("Server preview runtime")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    const runtimeOptions = screen.getAllByRole("button", {
      name: /WebAssembly/,
      hidden: true,
    });
    expect(runtimeOptions).toHaveLength(2);
    runtimeOptions.forEach((option) => expect(option).toBeDisabled());
    await user.click(runtimeOptions[0]!);
    expect(switchRuntime).not.toHaveBeenCalled();

    selection.resolve(false);
    await vi.waitFor(() => expect(views.getSnapshot().selecting).toBeUndefined());
    layout.dispose();
    preview.dispose();
    views.dispose();
  });

  it("restores the committed split when pointer capture is cancelled", () => {
    const tree = defaultWorkspaceLayout();
    const divider = computeLayout(tree, { left: 0, top: 0, width: 1005, height: 800 }).dividers[0];
    const workspace = document.createElement("main");
    workspace.getBoundingClientRect = () => new DOMRect(0, 0, 1005, 800);
    const onPreview = vi.fn();
    const onCommit = vi.fn();
    const onCancel = vi.fn();
    const onResize = vi.fn();
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((callback) => {
      callback(0);
      return 1;
    });
    render(
      <Divider
        divider={divider}
        tree={tree}
        workspace={workspace}
        onPreview={onPreview}
        onCommit={onCommit}
        onCancel={onCancel}
        onResize={onResize}
      />,
    );
    const separator = screen.getByRole("separator");
    Object.defineProperty(separator, "setPointerCapture", { value: vi.fn() });

    fireEvent.pointerDown(separator, { pointerId: 7, clientX: 502 });
    fireEvent.pointerMove(separator, { pointerId: 7, clientX: 700 });
    fireEvent.pointerCancel(separator, { pointerId: 7 });

    expect(onPreview).toHaveBeenCalled();
    expect(onCommit).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalled();
    expect(onResize).toHaveBeenLastCalledWith(null);
  });

  it("keeps primary mode navigation when a compact workspace has one surface", () => {
    const { layout, preview, views } = controllers();
    render(
      <Toolbar
        bootstrap={bootstrap}
        brand={brand}
        compact
        compactSurfaces={["notebook"]}
        preview={preview}
        views={views}
        layout={layout}
      />,
    );

    expect(screen.queryByRole("navigation", { name: "Studio surface" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("navigation", { name: "Studio mode" })[0]).toBeVisible();

    layout.dispose();
    preview.dispose();
    views.dispose();
  });

  it("retries in place when Studio rendering fails", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const retry = vi.fn();
    const Broken = () => {
      throw new Error("render failed");
    };

    render(
      <StudioErrorBoundary editorUrl="/?file=analysis.py" onRetry={retry}>
        <Broken />
      </StudioErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("render failed");
    await userEvent.click(screen.getByRole("button", { name: "Retry Studio" }));
    expect(retry).toHaveBeenCalledOnce();
    expect(screen.getByRole("link", { name: "Open the Marimo editor" })).toHaveAttribute(
      "href",
      "/?file=analysis.py",
    );
    log.mockRestore();
  });
});
