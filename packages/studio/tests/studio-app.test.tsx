import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from "react";
import { describe, expect, it, vi } from "vite-plus/test";

import type { SourceEditorHandle } from "../src/features/source-editor/SourceEditor.tsx";
import type { ViewRemote } from "../src/features/views/remote.ts";

import { createStudioServices } from "../src/app/services.ts";
import { StudioErrorBoundary } from "../src/app/StudioErrorBoundary.tsx";
import { Toolbar } from "../src/features/navigation/Toolbar.tsx";
import { PreviewDeck } from "../src/features/preview/deck.ts";
import { SourceController } from "../src/features/source-editor/controller.ts";
import { ViewController } from "../src/features/views/controller.ts";
import { LayoutController } from "../src/features/workspace/controller.ts";
import { Divider } from "../src/features/workspace/Divider.tsx";
import { computeLayout, defaultWorkspaceLayout } from "../src/features/workspace/model.ts";
import { useWorkspace } from "../src/features/workspace/useWorkspace.ts";
import { Workspace } from "../src/features/workspace/Workspace.tsx";

vi.mock("../src/features/source-editor/SourceEditor.tsx", () => ({
  SourceEditor: forwardRef<SourceEditorHandle>(function Editor(_props, ref) {
    const element = useRef<HTMLTextAreaElement>(null);
    useImperativeHandle(ref, () => ({
      focus: () => element.current?.focus(),
      requestMeasure: vi.fn(),
    }));
    return <textarea ref={element} aria-label="Source editor" />;
  }),
}));

const bootstrap: StudioBootstrap = {
  schema: 1,
  notebook: { name: "analysis.py" },
  selectedView: "dashboard",
  views: ["dashboard", "report"],
  runtimes: [
    { id: "server", label: "Server" },
    { id: "wasm", label: "WebAssembly" },
  ],
  defaultRuntime: "server",
  urls: {
    editor: "/?file=analysis.py",
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

const brand = {
  marks: {
    dark: "dark-mark.svg",
    light: "light-mark.svg",
  },
};

const remote = (): ViewRemote => {
  let views = ["dashboard", "report"];
  return {
    list: vi.fn(async () => ({
      schema: 1 as const,
      default_view: "dashboard",
      views,
    })),
    create: vi.fn(async (name: string) => {
      views = [...views, name].sort();
      return { schema: 1 as const, name };
    }),
    remove: vi.fn(async (name: string) => {
      views = views.filter((view) => view !== name);
      return {
        schema: 1 as const,
        name,
        default_view: "dashboard",
        views,
      };
    }),
  };
};

const controllers = () => {
  const layout = new LayoutController("test-workspace", bootstrap.selectedView);
  const preview = new PreviewDeck({
    initialView: bootstrap.selectedView,
    initialRuntime: bootstrap.defaultRuntime,
    runtimes: bootstrap.runtimes.map((runtime) => runtime.id),
    viewUrl: (view, runtime) => `/${view}/?runtime=${runtime}`,
    supportUrl: (view) => `/_marimo-studio/views/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => undefined),
    navigate: vi.fn(),
  });
  const views = new ViewController(
    bootstrap.selectedView,
    [...bootstrap.views],
    remote(),
    bootstrap.urls.events,
    vi.fn(async () => true),
    vi.fn(async () => true),
    vi.fn(),
  );
  const source = new SourceController(
    bootstrap.urls.viewSupportPrefix,
    bootstrap.serverToken,
    bootstrap.selectedView,
    "test-workspace",
    () => layout.reveal("source"),
  );
  return { layout, preview, source, views };
};

const WorkspaceHarness = ({
  frames,
  layout,
  preview,
  source,
  views,
}: ReturnType<typeof controllers> & { frames: Map<string, HTMLIFrameElement> }) => {
  const workspace = useWorkspace(layout, preview, views);
  const editor = useRef<HTMLIFrameElement | null>(null);
  useLayoutEffect(() => {
    if (!editor.current) {
      return;
    }
    frames.forEach((frame, runtime) => {
      frame.src = `/${bootstrap.selectedView}/?runtime=${runtime}`;
    });
    preview.attach(editor.current, frames);
  }, [frames, preview]);
  return (
    <Workspace
      bootstrap={bootstrap}
      editorRef={(element) => {
        editor.current = element;
      }}
      frameRef={(runtime) => (element) => {
        if (element) {
          frames.set(runtime, element);
        } else {
          frames.delete(runtime);
        }
      }}
      source={source}
      workspace={workspace}
    />
  );
};

describe("Studio shell", () => {
  it("restores persisted layout trees and source tab from the application namespace", () => {
    const storagePrefix = `marimo-studio:workspace-layout:v1:${bootstrap.workspaceId}`;
    const persisted = {
      schema: 1,
      mode: "workspace",
      code: { type: "pane", id: "pane-source", surface: "source" },
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
    globalThis.localStorage.setItem(
      `${storagePrefix}:source:${bootstrap.selectedView}`,
      "theme.css",
    );

    const services = createStudioServices(bootstrap);

    expect(services.layout.getSnapshot().code).toEqual(persisted.code);
    expect(services.layout.getSnapshot().workspace).toEqual(persisted.workspace);
    expect(services.source.getSnapshot().active).toBe("theme.css");
    services.dispose();
  });

  it("keeps toolbar modes and preview runtimes synchronized", async () => {
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

    expect(screen.getAllByRole("button", { name: "Build" })[0]).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByLabelText("Server preview runtime")).toHaveTextContent("Server");

    await user.click(screen.getByLabelText("Workspace options"));
    let overflow = within(screen.getAllByRole("navigation", { name: "Studio mode" }).at(-1)!);
    expect(overflow.getByRole("button", { name: "Build" })).toHaveAttribute("aria-pressed", "true");
    await user.click(overflow.getByRole("button", { name: "HTML & CSS" }));

    await user.click(screen.getByLabelText("Workspace options"));
    overflow = within(screen.getAllByRole("navigation", { name: "Studio mode" }).at(-1)!);
    expect(overflow.getByRole("button", { name: "Build" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(overflow.getByRole("button", { name: "HTML & CSS" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByLabelText("Workspace options"));

    await user.click(screen.getAllByRole("button", { name: "Preview" })[0]);
    expect(screen.getAllByRole("button", { name: "Preview" })[0]).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByLabelText("Server preview runtime"));
    await user.click(screen.getAllByRole("button", { name: /WebAssembly.*Runs locally/ })[0]);
    expect(screen.getByLabelText("WebAssembly preview runtime")).toBeVisible();

    layout.dispose();
    preview.dispose();
    views.dispose();
  });

  it("creates a view from the view menu and selects it", async () => {
    const user = userEvent.setup();
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

    await user.click(screen.getByLabelText("Select or manage a view"));
    await user.click(screen.getByRole("button", { name: "+ New view" }));
    await user.type(screen.getByRole("textbox", { name: "New view" }), "exploration");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(screen.getByLabelText("Select or manage a view")).toHaveTextContent("exploration");
    expect(screen.getByLabelText("Select or manage a view")).toHaveFocus();

    layout.dispose();
    preview.dispose();
    views.dispose();
  });

  it("moves focus into view removal and restores its origin on cancel", async () => {
    const user = userEvent.setup();
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

    await user.click(screen.getByLabelText("Select or manage a view"));
    const origin = screen.getByRole("button", { name: "Remove report view" });
    await user.click(origin);
    expect(screen.getByRole("button", { name: "Remove" })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await act(async () => {
      await new Promise<void>((resolve) => globalThis.requestAnimationFrame(() => resolve()));
    });
    expect(origin).toHaveFocus();

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

  it("keeps notebook and preview iframe identities across UI state changes", async () => {
    const { layout, preview, source, views } = controllers();
    const frames = new Map<string, HTMLIFrameElement>();
    render(
      <WorkspaceHarness
        frames={frames}
        preview={preview}
        source={source}
        views={views}
        layout={layout}
      />,
    );

    const notebook = screen.getByTitle("Marimo editor");
    const server = screen.getByTitle("dashboard custom view using server");
    const notebookWindow = (notebook as HTMLIFrameElement).contentWindow;
    const serverWindow = (server as HTMLIFrameElement).contentWindow;
    const wasm = screen.getByTitle("dashboard custom view using wasm");
    for (const [runtime, frame] of [
      ["server", server],
      ["wasm", wasm],
    ] as const) {
      globalThis.dispatchEvent(
        new MessageEvent("message", {
          origin: globalThis.location.origin,
          source: (frame as HTMLIFrameElement).contentWindow,
          data: {
            type: "marimo-studio:receiver-ready",
            runtime,
            view: "dashboard",
          },
        }),
      );
    }

    act(() => layout.selectMode("notebook"));
    act(() => preview.switchRuntime("wasm"));
    await act(async () => await views.choose("report"));
    act(() => preview.switchView("report"));

    expect(screen.getByTitle("Marimo editor")).toBe(notebook);
    expect(frames.get("server")).toBe(server);
    expect((notebook as HTMLIFrameElement).contentWindow).toBe(notebookWindow);
    expect((server as HTMLIFrameElement).contentWindow).toBe(serverWindow);
    expect(server).toHaveAttribute("data-preview-frame");
    expect(server).toHaveAttribute("data-preview-runtime-frame", "server");

    layout.dispose();
    preview.dispose();
    source.dispose();
    views.dispose();
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

  it("links back to the notebook when Studio rendering fails", () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const Broken = () => {
      throw new Error("render failed");
    };

    render(
      <StudioErrorBoundary editorUrl="/?file=analysis.py">
        <Broken />
      </StudioErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("render failed");
    expect(screen.getByRole("link", { name: "Open the Marimo editor" })).toHaveAttribute(
      "href",
      "/?file=analysis.py",
    );
    log.mockRestore();
  });
});
