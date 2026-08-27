import type { SourceDocumentPath } from "@marimo-studio/protocol/source-documents";
import type { ProjectDiagnostic, ViewProject } from "@marimo-studio/protocol/view-project";

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EditorView } from "@uiw/react-codemirror";
import { expect, it, vi } from "vite-plus/test";

import type { RemoteSource, SourceRemote } from "../src/features/source-editor/remote.ts";

import { SourceController } from "../src/features/source-editor/controller.ts";
import { SourcePane } from "../src/features/source-editor/SourcePane.tsx";
import { SourceProjectDetails } from "../src/features/source-editor/SourceProjectDetails.tsx";
import { unbuiltView } from "./fixtures.ts";

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
};

const documents: ViewProject["documents"] = [
  { path: "src/App.svelte", language: "svelte", access: "edit" },
  { path: "src/components/MetricCard.svelte", language: "svelte", access: "edit" },
  { path: "src/state.ts", language: "typescript", access: "edit" },
  { path: "src/theme.css", language: "css", access: "edit" },
  { path: "src/index.html", language: "html", access: "edit" },
  { path: "vite.config.ts", language: "typescript", access: "edit" },
  { path: "deno.lock", language: "json", access: "read" },
];
const searchShortcut = "{Control>}f{/Control}";
const undoShortcut = "{Control>}z{/Control}";

const editorView = (element: HTMLElement): EditorView => {
  const view = EditorView.findFromDOM(element);
  if (!view) {
    throw new Error("The source editor did not expose its CodeMirror view");
  }
  return view;
};

class PaneRemote implements SourceRemote {
  private readonly sources = new Map<SourceDocumentPath, RemoteSource>();
  private documents = [...documents];
  private failedView: string | undefined;

  constructor(
    private readonly diagnostics: readonly ProjectDiagnostic[] = [],
    private readonly projectOverrides: Partial<ViewProject> = {},
  ) {}

  project(view: string): Promise<ViewProject> {
    return Promise.resolve({
      schema: 1,
      view,
      provider: "marimo-studio/svelte",
      provider_options: {},
      documents: this.documents,
      mounts: [],
      diagnostics: [...this.diagnostics],
      build: unbuiltView,
      artifact: null,
      ...this.projectOverrides,
    });
  }

  read(view: string, path: SourceDocumentPath): Promise<RemoteSource> {
    if (view === this.failedView) {
      return Promise.reject(new Error(`Source unavailable for ${view}`));
    }
    return Promise.resolve(
      this.sources.get(path) ?? { content: `source:${path}`, revision: `revision:${path}` },
    );
  }

  write(
    _view: string,
    _path: SourceDocumentPath,
    _content: string,
    revision: string,
  ): Promise<string> {
    const next = `${revision}-next`;
    this.sources.set(_path, { content: _content, revision: next });
    return Promise.resolve(next);
  }

  setSource(path: SourceDocumentPath, source: RemoteSource): void {
    this.sources.set(path, source);
  }

  failSourceFor(view: string): void {
    this.failedView = view;
  }

  setDocuments(next: ViewProject["documents"]): void {
    this.documents = [...next];
  }
}

it("switches one editor between editable and read-only provider documents", async () => {
  Object.defineProperties(Range.prototype, {
    getBoundingClientRect: { configurable: true, value: () => new DOMRect() },
    getClientRects: { configurable: true, value: () => [] },
  });
  const user = userEvent.setup();
  const controller = new SourceController(
    vi.fn(),
    "token",
    "svelte",
    "source-pane-test",
    vi.fn(),
    new PaneRemote(),
  );
  await controller.start();

  render(<SourcePane controller={controller} visible />);
  const tabs = screen.getAllByRole("tab");
  expect(tabs).toHaveLength(documents.length);
  expect(await screen.findByLabelText("src/App.svelte source")).toHaveAttribute(
    "aria-readonly",
    "false",
  );
  expect(screen.getAllByLabelText(/ source$/)).toHaveLength(1);

  await user.click(screen.getByRole("tab", { name: /deno\.lock/ }));

  const lockEditor = await screen.findByLabelText("deno.lock source");
  expect(lockEditor).toHaveAttribute("aria-readonly", "true");
  expect(lockEditor).toHaveAttribute("contenteditable", "false");
  expect(lockEditor).toHaveAttribute("tabindex", "0");
  expect(screen.getAllByLabelText(/ source$/)).toHaveLength(1);
  await user.keyboard("{Home}");
  expect(screen.getByRole("tab", { name: "src/App.svelte" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await vi.waitFor(() => expect(screen.getByRole("tab", { name: "src/App.svelte" })).toHaveFocus());
  await user.keyboard("{Tab}");
  expect(screen.getByLabelText("src/App.svelte source")).toHaveFocus();
  controller.dispose();
});

it("includes a provider label and source path in a tab's accessible name", async () => {
  const controller = new SourceController(
    vi.fn(),
    "token",
    "svelte",
    "source-tab-label-test",
    vi.fn(),
    new PaneRemote([], {
      documents: [{ ...documents[0], label: "Main component" }],
    }),
  );
  await controller.start();

  render(<SourcePane controller={controller} visible />);

  expect(screen.getByRole("tab", { name: "Main component, src/App.svelte" })).toHaveTextContent(
    "Main component",
  );
  controller.dispose();
});

it("keeps provider diagnostics visible when no source documents are exposed", async () => {
  const diagnostic: ProjectDiagnostic = {
    code: "entry-document-invalid",
    severity: "error",
    message: "The configured entry document is missing.",
    hint: "Restore the entry document and build the view again.",
    source: null,
  };
  const controller = new SourceController(
    vi.fn(),
    "token",
    "vanilla",
    "source-empty-catalog-test",
    vi.fn(),
    new PaneRemote([diagnostic], { documents: [] }),
  );

  await controller.start();
  render(<SourcePane controller={controller} visible />);

  expect(controller.getSnapshot()).toMatchObject({
    phase: "ready",
    view: "vanilla",
    active: null,
    documents: [],
    inspection: { phase: "ready" },
    diagnostics: [diagnostic],
  });
  expect(screen.getByRole("status", { name: "Source document status" })).toHaveTextContent(
    "No source documents",
  );
  expect(screen.getByText("This view has no source files to edit.")).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent(diagnostic.message);
  controller.dispose();
});

it("shows an HTTP conflict recovery path in the Source pane", async () => {
  const path = "src/App.tsx" as const;
  let writeAttempted = false;
  vi.stubGlobal("fetch", async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(input instanceof Request ? input.url : input.toString());
    if (url.pathname.endsWith("/project")) {
      return Response.json({
        schema: 1,
        view: "react",
        provider: "marimo-studio/react",
        provider_options: {},
        documents: [{ path, language: "typescriptreact", access: "edit", label: null }],
        mounts: [],
        diagnostics: [],
        build: unbuiltView,
        artifact: null,
      });
    }
    const method = init?.method ?? (input instanceof Request ? input.method : "GET");
    if (method === "PUT") {
      writeAttempted = true;
      return Response.json(
        {
          error: "source-conflict",
          message: `${path} changed on disk.`,
          revision: "sha256:disk",
          external_recovery: "/workspace/.App.tsx.external-recovery",
        },
        { status: 412 },
      );
    }
    return new Response(writeAttempted ? "disk source" : "initial source", {
      headers: { ETag: writeAttempted ? '"sha256:disk"' : '"sha256:initial"' },
    });
  });
  const controller = new SourceController(
    (view) => `http://localhost/_marimo-studio/views/${view}`,
    "token",
    "react",
    "source-http-conflict-test",
    vi.fn(),
  );
  await controller.start();
  render(<SourcePane controller={controller} visible />);

  controller.edit(path, "local source");
  controller.save(path);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Previous disk content is preserved at /workspace/.App.tsx.external-recovery.",
  );
  controller.dispose();
});

it("preserves editor history, selection, and scroll for each opened document", async () => {
  Object.defineProperties(Range.prototype, {
    getBoundingClientRect: { configurable: true, value: () => new DOMRect() },
    getClientRects: { configurable: true, value: () => [] },
  });
  const user = userEvent.setup();
  const controller = new SourceController(
    vi.fn(),
    "token",
    "svelte",
    "source-editor-state-test",
    vi.fn(),
    new PaneRemote(),
  );
  await controller.start();
  const { container } = render(<SourcePane controller={controller} visible />);
  let app = await screen.findByLabelText("src/App.svelte source");
  app.focus();
  await user.keyboard("{End}X");
  expect(app).toHaveTextContent("source:src/App.svelteX");
  const initialScroller = editorView(app).scrollDOM;
  initialScroller.scrollTop = 72;
  initialScroller.scrollLeft = 11;

  await user.click(screen.getByRole("tab", { name: "src/theme.css" }));
  await screen.findByLabelText("src/theme.css source");
  await user.click(screen.getByRole("tab", { name: "src/App.svelte" }));
  app = await screen.findByLabelText("src/App.svelte source");
  await vi.waitFor(() => {
    const restoredScroller = editorView(app).scrollDOM;
    expect(restoredScroller).toBe(initialScroller);
    expect(restoredScroller.scrollTop).toBe(72);
    expect(restoredScroller.scrollLeft).toBe(11);
  });
  app.focus();
  await user.keyboard("Y");
  expect(app).toHaveTextContent("source:src/App.svelteXY");
  await user.keyboard(undoShortcut);
  await user.keyboard(undoShortcut);
  expect(app).toHaveTextContent("source:src/App.svelte");

  await user.keyboard(searchShortcut);
  const search = container.querySelector<HTMLInputElement>('input[name="search"]');
  expect(search).not.toBeNull();
  await user.type(search!, "App");
  await user.click(screen.getByRole("tab", { name: "src/theme.css" }));
  await screen.findByLabelText("src/theme.css source");
  await user.click(screen.getByRole("tab", { name: "src/App.svelte" }));
  await screen.findByLabelText("src/App.svelte source");
  expect(container.querySelector<HTMLInputElement>('input[name="search"]')).toHaveValue("App");
  controller.dispose();
});

it("resets undo history for an authoritative external source replacement", async () => {
  Object.defineProperties(Range.prototype, {
    getBoundingClientRect: { configurable: true, value: () => new DOMRect() },
    getClientRects: { configurable: true, value: () => [] },
  });
  const user = userEvent.setup();
  const remote = new PaneRemote();
  const controller = new SourceController(
    vi.fn(),
    "token",
    "svelte",
    "source-authoritative-replacement-test",
    vi.fn(),
    remote,
  );
  await controller.start();
  render(<SourcePane controller={controller} visible />);
  const app = await screen.findByLabelText("src/App.svelte source");
  app.focus();
  await user.keyboard("{End}X");
  controller.save("src/App.svelte");
  await vi.waitFor(() => expect(controller.getSnapshot().documents[0]?.state.phase).toBe("saved"));
  const scroller = editorView(app).scrollDOM;
  scroller.scrollTop = 48;
  scroller.scrollLeft = 9;
  remote.setSource("src/App.svelte", {
    content: "authoritative",
    revision: "revision:external",
  });

  controller.externalChanges([{ path: "src/App.svelte", revision: "revision:external" }]);

  await vi.waitFor(() => expect(app).toHaveTextContent("authoritative"));
  expect(scroller?.scrollTop).toBe(48);
  expect(scroller?.scrollLeft).toBe(9);
  app.focus();
  await user.keyboard(undoShortcut);
  expect(app).toHaveTextContent("authoritative");
  await user.keyboard("Y");
  expect(app).toHaveTextContent("authoritativeY");
  controller.dispose();
});

it("starts recreated document incarnations with fresh editor state", async () => {
  Object.defineProperties(Range.prototype, {
    getBoundingClientRect: { configurable: true, value: () => new DOMRect() },
    getClientRects: { configurable: true, value: () => [] },
  });
  const user = userEvent.setup();
  const remote = new PaneRemote();
  const controller = new SourceController(
    vi.fn(),
    "token",
    "svelte",
    "source-document-incarnation-test",
    vi.fn(),
    remote,
  );
  await controller.start();
  render(<SourcePane controller={controller} visible />);
  let app = await screen.findByLabelText("src/App.svelte source");
  app.focus();
  await user.keyboard("{End}X");
  controller.save("src/App.svelte");
  await vi.waitFor(() => expect(controller.getSnapshot().documents[0]?.state.phase).toBe("saved"));
  remote.setDocuments(documents.filter(({ path }) => path !== "src/App.svelte"));
  controller.externalChanges([{ path: "src/App.svelte", revision: null }]);
  await vi.waitFor(() =>
    expect(screen.queryByRole("tab", { name: "src/App.svelte" })).not.toBeInTheDocument(),
  );
  remote.setSource("src/App.svelte", { content: "recreated", revision: "revision:recreated" });
  remote.setDocuments(documents);
  controller.externalChanges([{ path: "src/App.svelte", revision: "revision:recreated" }]);
  await user.click(await screen.findByRole("tab", { name: "src/App.svelte" }));
  app = await screen.findByLabelText("src/App.svelte source");

  expect(app).toHaveTextContent("recreated");
  app.focus();
  await user.keyboard(undoShortcut);
  expect(app).toHaveTextContent("recreated");
  controller.dispose();
});

it("shows the active document diagnostic and marks each tab with its highest severity", async () => {
  const user = userEvent.setup();
  const diagnostics: ProjectDiagnostic[] = [
    {
      code: "app-warning",
      severity: "warning",
      message: "App warning",
      hint: "Review the app.",
      source: { path: "src/App.svelte", line: 1, column: 1 },
    },
    {
      code: "theme-warning",
      severity: "warning",
      message: "Theme warning",
      hint: "Review the theme.",
      source: { path: "src/theme.css", line: 1, column: 1 },
    },
    {
      code: "theme-error",
      severity: "error",
      message: "Theme error",
      hint: "Repair the theme.",
      source: { path: "src/theme.css", line: 2, column: 1 },
    },
  ];
  const controller = new SourceController(
    vi.fn(),
    "token",
    "svelte",
    "source-diagnostic-test",
    vi.fn(),
    new PaneRemote(diagnostics),
  );
  await controller.start();

  render(<SourcePane controller={controller} visible />);
  const appTab = screen.getByRole("tab", { name: "src/App.svelte" });
  const themeTab = screen.getByRole("tab", { name: "src/theme.css" });
  expect(appTab).toHaveAttribute("data-diagnostic", "warning");
  expect(themeTab).toHaveAttribute("data-diagnostic", "error");
  expect(appTab).toHaveAccessibleDescription("Warning: App warning");
  expect(themeTab).toHaveAccessibleDescription("Error: Theme error");
  const warning = screen
    .getAllByRole("status")
    .find((candidate) => candidate.textContent?.includes("App warning"));
  expect(warning).toHaveTextContent("App warning");

  await user.click(themeTab);

  expect(screen.getByRole("alert")).toHaveTextContent("Theme error");
  controller.dispose();
});

it("keeps project evidence behind the build status disclosure", async () => {
  const build = {
    ...unbuiltView,
    phase: "stale" as const,
    project_revision: "sha256:project-current",
    artifact_revision: "sha256:artifact-published",
    diagnostics: [
      {
        code: "build-action",
        severity: "error" as const,
        message: "Rebuild the current source.",
        hint: "Save the source, then rebuild.",
        source: null,
      },
    ],
  };
  const artifact = {
    profile: "development" as const,
    input_id: "sha256:project-published",
    artifact_id: "sha256:artifact-published",
  };
  const controller = new SourceController(
    vi.fn(),
    "token",
    "svelte",
    "source-project-context-test",
    vi.fn(),
    new PaneRemote([], { build, artifact }),
  );
  await controller.start();

  const user = userEvent.setup();
  render(<SourcePane controller={controller} visible />);
  const projectDetails = screen.getByLabelText("View project details");
  const trigger = screen.getByLabelText("View build details, Build needed");
  expect(projectDetails).not.toBeVisible();
  await user.click(trigger);
  expect(projectDetails).toBeVisible();
  expect(projectDetails).toHaveTextContent("marimo-studio/svelte");
  expect(projectDetails).toHaveTextContent("project-cu");
  expect(projectDetails).toHaveTextContent("artifact-p");
  expect(projectDetails).toHaveTextContent("Source is newer than the published view.");
  expect(projectDetails).toHaveTextContent("Rebuild the current source.");
  expect(within(projectDetails).getByTitle("sha256:project-current")).toBeVisible();
  expect(within(projectDetails).getByTitle("sha256:artifact-published")).toBeVisible();
  await user.keyboard("{Escape}");
  await vi.waitFor(() => expect(trigger).toHaveFocus());
  expect(projectDetails).not.toBeVisible();
  controller.dispose();
});

it("explains when build freshness is unavailable", async () => {
  const build = {
    ...unbuiltView,
    phase: "published" as const,
    project_revision: "sha256:project-current",
    artifact_revision: "sha256:artifact-current",
  };
  const artifact = {
    profile: "development" as const,
    input_id: "sha256:project-current",
    artifact_id: "sha256:artifact-current",
  };
  const user = userEvent.setup();
  render(
    <SourceProjectDetails
      artifact={artifact}
      build={build}
      inspection={{ phase: "unavailable", message: "Inspection unavailable" }}
      provider="marimo-studio/svelte"
    />,
  );
  const trigger = screen.getByLabelText("View build details, Build status unavailable");
  expect(trigger).toBeVisible();

  await user.click(trigger);
  expect(screen.getByLabelText("View project details")).toHaveTextContent("Inspection unavailable");
  expect(screen.getByLabelText("View project details")).toHaveTextContent("Last checked revision");
});

it("describes an inactive source conflict from its tab", async () => {
  const remote = new PaneRemote();
  const controller = new SourceController(
    vi.fn(),
    "token",
    "svelte",
    "source-conflict-description-test",
    vi.fn(),
    remote,
  );
  await controller.start();
  controller.edit("src/App.svelte", "local app");
  remote.setSource("src/App.svelte", { content: "external app", revision: "revision:external" });
  controller.externalChanges([{ path: "src/App.svelte", revision: "revision:external" }]);
  await vi.waitFor(() =>
    expect(controller.getSnapshot().documents[0]?.state.phase).toBe("conflict"),
  );
  controller.activate("src/theme.css");

  render(<SourcePane controller={controller} visible />);

  expect(screen.getByRole("tab", { name: "src/App.svelte" })).toHaveAccessibleDescription(
    "Conflict: changed on disk while you were editing",
  );
  controller.dispose();
});

it("renders a failed source diagnostic for the selected view", async () => {
  const remote = new PaneRemote();
  const controller = new SourceController(
    vi.fn(),
    "token",
    "svelte",
    "source-target-diagnostic-test",
    vi.fn(),
    remote,
  );
  await controller.start();
  remote.failSourceFor("broken");

  controller.selectView("broken");
  await vi.waitFor(() =>
    expect(controller.getSnapshot().targetDiagnostic).toMatchObject({ view: "broken" }),
  );
  render(<SourcePane controller={controller} visible />);

  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent("Could not open src/App.svelte.");
  expect(alert).toHaveTextContent("Source unavailable for broken");
  expect(screen.queryByLabelText("src/App.svelte source")).toBeNull();
  controller.dispose();
});

it("announces source loading while a selected view hydrates", async () => {
  const pending = deferred<ViewProject>();
  const remote = new PaneRemote();
  const project = vi.spyOn(remote, "project").mockImplementation((view) => {
    if (view === "pending") {
      return pending.promise;
    }
    return Promise.resolve({
      schema: 1,
      view,
      provider: "marimo-studio/svelte",
      provider_options: {},
      documents,
      mounts: [],
      diagnostics: [],
      build: unbuiltView,
      artifact: null,
    });
  });
  const controller = new SourceController(
    vi.fn(),
    "token",
    "svelte",
    "source-pending-test",
    vi.fn(),
    remote,
  );
  await controller.start();
  render(<SourcePane controller={controller} visible />);

  controller.selectView("pending");

  expect(controller.getSnapshot()).toMatchObject({
    phase: "loading",
    view: "pending",
    documents: [],
  });
  await vi.waitFor(() => expect(screen.getAllByText("Loading source documents")).toHaveLength(2));
  pending.resolve({
    schema: 1,
    view: "pending",
    provider: "marimo-studio/svelte",
    provider_options: {},
    documents,
    mounts: [],
    diagnostics: [],
    build: unbuiltView,
    artifact: null,
  });
  await vi.waitFor(() => expect(controller.getSnapshot().phase).toBe("ready"));
  expect(project).toHaveBeenCalledWith("pending");
  controller.dispose();
});
