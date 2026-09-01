import type { SourceDocumentPath } from "@marimo-studio/protocol/source-documents";
import type { ViewProject } from "@marimo-studio/protocol/view-project";

import { expect, it, vi } from "vite-plus/test";

import type { RemoteSource, SourceRemote } from "../src/features/source-editor/remote.ts";

import { SourceController } from "../src/features/source-editor/controller.ts";
import { unbuiltView, viewOwner } from "./fixtures.ts";

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (cause: Error) => void;
  const promise = new Promise<T>((complete, fail) => {
    resolve = complete;
    reject = fail;
  });
  return { promise, reject, resolve };
};

const document = (
  path: SourceDocumentPath,
  language: string,
  access: "edit" | "read" = "edit",
) => ({ path, language, access });

const project = (
  view: string,
  documents: ViewProject["documents"],
  provider = `test/${view}`,
): ViewProject => ({
  schema: 1,
  ...viewOwner,
  view,
  provider,
  provider_options: {},
  documents,
  mounts: [],
  diagnostics: [],
  build: unbuiltView,
  artifact: null,
});

class MemorySourceRemote implements SourceRemote {
  readonly writes: Array<{ view: string; path: SourceDocumentPath; content: string }> = [];
  readonly reads: string[] = [];
  readonly inspections: string[] = [];
  readonly files = new Map<string, RemoteSource>();
  readonly projects = new Map<string, ViewProject>();

  project(view: string): Promise<ViewProject> {
    this.inspections.push(view);
    const current = this.projects.get(view);
    if (!current) {
      return Promise.reject(new Error(`Missing project ${view}`));
    }
    return Promise.resolve(current);
  }

  read(view: string, path: SourceDocumentPath): Promise<RemoteSource> {
    this.reads.push(`${view}:${path}`);
    const source = this.files.get(`${view}:${path}`);
    if (!source) {
      return Promise.reject(new Error(`Missing source ${path}`));
    }
    return Promise.resolve({ ...source });
  }

  write(
    view: string,
    path: SourceDocumentPath,
    content: string,
    revision: string,
  ): Promise<string> {
    const key = `${view}:${path}`;
    const next = `${revision}-next`;
    this.files.set(key, { content, revision: next });
    this.writes.push({ view, path, content });
    return Promise.resolve(next);
  }

  setProject(view: string, documents: ViewProject["documents"], provider?: string): void {
    this.projects.set(view, project(view, documents, provider));
    for (const { path } of documents) {
      this.files.set(`${view}:${path}`, {
        content: `source:${view}:${path}`,
        revision: `revision:${view}:${path}`,
      });
    }
  }
}

class DeferredSourceRemote extends MemorySourceRemote {
  private readonly deferredReads = new Map<string, ReturnType<typeof deferred<RemoteSource>>>();

  deferRead(view: string, path: SourceDocumentPath): ReturnType<typeof deferred<RemoteSource>> {
    const pending = deferred<RemoteSource>();
    this.deferredReads.set(`${view}:${path}`, pending);
    return pending;
  }

  override read(view: string, path: SourceDocumentPath): Promise<RemoteSource> {
    const pending = this.deferredReads.get(`${view}:${path}`);
    if (!pending) {
      return super.read(view, path);
    }
    this.reads.push(`${view}:${path}`);
    this.deferredReads.delete(`${view}:${path}`);
    return pending.promise;
  }
}

const controller = (remote: SourceRemote, view = "react") =>
  new SourceController(vi.fn(), "token", view, "source-controller-test", vi.fn(), remote);

const selectSourceView = async (source: SourceController, view: string): Promise<void> => {
  source.selectView(view);
  await vi.waitFor(() => {
    expect(source.getSnapshot().view).toBe(view);
    expect(source.getSnapshot().documents.length).toBeGreaterThan(0);
  });
};

it.each(["project", "source"] as const)(
  "recovers from an initial %s failure after a later reconcile",
  async (failure) => {
    const remote = new MemorySourceRemote();
    if (failure === "source") {
      remote.setProject("react", [document("src/App.tsx", "typescriptreact")]);
      remote.files.delete("react:src/App.tsx");
    }
    const source = controller(remote);

    await source.start();

    expect(source.getSnapshot().documents).toEqual([]);
    if (failure === "project") {
      remote.setProject("react", [document("src/App.tsx", "typescriptreact")]);
    } else {
      remote.files.set("react:src/App.tsx", {
        content: "recovered source",
        revision: "revision:recovered",
      });
    }
    source.reconcile();

    await vi.waitFor(() =>
      expect(source.getSnapshot()).toMatchObject({
        view: "react",
        active: "src/App.tsx",
        documents: [{ path: "src/App.tsx", loaded: true }],
        targetDiagnostic: undefined,
      }),
    );
    source.dispose();
  },
);

it("loads provider documents in order and enforces read-only access", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [
    document("src/App.tsx", "typescriptreact"),
    document("src/theme.css", "css"),
    document("deno.lock", "json", "read"),
  ]);
  globalThis.localStorage.setItem("source-controller-test:source:react", "deno.lock");
  const source = controller(remote);

  await source.start();

  expect(source.getSnapshot()).toMatchObject({
    view: "react",
    provider: "test/react",
    active: "deno.lock",
  });
  expect(source.getSnapshot().documents.map(({ path }) => path)).toEqual([
    "src/App.tsx",
    "src/theme.css",
    "deno.lock",
  ]);
  expect(remote.inspections).toEqual(["react"]);
  expect(remote.reads).toEqual(["react:deno.lock"]);
  source.edit("deno.lock", "changed");
  source.save("deno.lock");
  expect(remote.writes).toEqual([]);
  expect(source.hasPendingChanges).toBe(false);

  source.dispose();
});

it("falls back when a persisted document is absent from the current catalog", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [
    document("src/App.tsx", "typescriptreact"),
    document("src/theme.css", "css"),
  ]);
  globalThis.localStorage.setItem("source-controller-test:source:react", "src/removed.ts");
  const source = controller(remote);

  await source.start();

  expect(source.getSnapshot().active).toBe("src/App.tsx");
  expect(source.getSnapshot().documents.map(({ path }) => path)).toEqual([
    "src/App.tsx",
    "src/theme.css",
  ]);
  expect(remote.reads).toEqual(["react:src/App.tsx"]);
  expect(globalThis.localStorage.getItem("source-controller-test:source:react")).toBe(
    "src/App.tsx",
  );
  source.dispose();
});

it("replaces the active session when the same view gets a new owner", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [document("src/App.tsx", "typescriptreact")]);
  const source = controller(remote);

  await source.start();
  remote.files.set("react:src/App.tsx", {
    content: "replacement source",
    revision: "revision:react:replacement",
  });
  source.replaceView("react");

  await vi.waitFor(() => {
    expect(remote.inspections).toEqual(["react", "react"]);
    expect(source.getSnapshot().documents[0]).toMatchObject({
      content: "replacement source",
      loaded: true,
    });
  });
  expect(remote.reads).toEqual(["react:src/App.tsx", "react:src/App.tsx"]);
  expect(remote.writes).toEqual([]);
  source.dispose();
});

it("keeps unsaved source visible when the view owner is replaced", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [document("src/App.tsx", "typescriptreact")]);
  const source = controller(remote);

  await source.start();
  source.edit("src/App.tsx", "stale buffered source");
  source.replaceView("react");

  expect(source.getSnapshot()).toMatchObject({
    inspection: {
      phase: "unavailable",
      message:
        "View react was replaced. Unsaved edits remain in Source. Copy them before reopening the view.",
    },
    documents: [{ content: "stale buffered source", loaded: true }],
  });
  expect(remote.inspections).toEqual(["react"]);
  expect(remote.writes).toEqual([]);
  source.dispose();
});

it("loads the active document and fetches another document on first activation", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("dashboard", [
    document("src/App.tsx", "typescriptreact"),
    document("src/components/MetricCard.tsx", "typescriptreact"),
    document("deno.lock", "json", "read"),
  ]);
  const source = controller(remote, "dashboard");

  await source.start();

  expect(remote.inspections).toEqual(["dashboard"]);
  expect(remote.reads).toEqual(["dashboard:src/App.tsx"]);
  source.activate("src/components/MetricCard.tsx");
  await vi.waitFor(() =>
    expect(remote.reads).toEqual([
      "dashboard:src/App.tsx",
      "dashboard:src/components/MetricCard.tsx",
    ]),
  );
  source.activate("src/components/MetricCard.tsx");
  await Promise.resolve();
  expect(remote.reads).toEqual([
    "dashboard:src/App.tsx",
    "dashboard:src/components/MetricCard.tsx",
  ]);
  source.dispose();
});

it("restores the active source path independently for each view", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [
    document("src/App.tsx", "typescriptreact"),
    document("src/theme.css", "css"),
  ]);
  remote.setProject("svelte", [
    document("src/App.svelte", "svelte"),
    document("src/theme.css", "css"),
  ]);
  const source = controller(remote);
  await source.start();
  source.activate("src/theme.css");

  await selectSourceView(source, "svelte");
  expect(source.getSnapshot().active).toBe("src/App.svelte");
  source.activate("src/theme.css");
  await selectSourceView(source, "react");

  expect(source.getSnapshot().active).toBe("src/theme.css");
  source.dispose();
});

it("keeps a restored orphan read-only when the provider restores read access", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [document("src/App.tsx", "typescriptreact")]);
  const source = controller(remote);
  await source.start();
  source.edit("src/App.tsx", "local draft");
  remote.setProject("react", [document("src/theme.css", "css")]);
  source.externalChanges([]);
  await vi.waitFor(() =>
    expect(source.getSnapshot().documents.find(({ path }) => path === "src/App.tsx")).toMatchObject(
      {
        state: { conflict: { kind: "orphan" } },
      },
    ),
  );
  remote.setProject("react", [document("src/App.tsx", "typescriptreact", "read")]);

  source.externalChanges([]);

  await vi.waitFor(() =>
    expect(source.getSnapshot().documents[0]).toMatchObject({
      path: "src/App.tsx",
      access: "read",
      state: { phase: "conflict", conflict: { kind: "read-only" } },
    }),
  );
  source.overwriteSavedVersion();
  await Promise.resolve();
  expect(remote.writes).toEqual([]);
  source.dispose();
});

it("selects the target immediately after the current source flushes", async () => {
  const remote = new DeferredSourceRemote();
  remote.setProject("react", [document("src/App.tsx", "typescriptreact")]);
  remote.setProject("svelte", [document("src/App.svelte", "svelte")]);
  const target = remote.deferRead("svelte", "src/App.svelte");
  const source = controller(remote);
  await source.start();
  source.edit("src/App.tsx", "saved before switch");

  expect(await source.prepareViewChange()).toBe(true);
  source.selectView("svelte");
  await vi.waitFor(() => expect(remote.reads).toContain("svelte:src/App.svelte"));
  expect(source.getSnapshot()).toMatchObject({
    phase: "loading",
    view: "svelte",
    active: null,
    documents: [],
  });
  expect(remote.writes).toContainEqual({
    view: "react",
    path: "src/App.tsx",
    content: "saved before switch",
  });
  target.resolve({ content: "svelte source", revision: "revision:svelte" });

  await vi.waitFor(() =>
    expect(source.getSnapshot()).toMatchObject({
      view: "svelte",
      active: "src/App.svelte",
      documents: [{ path: "src/App.svelte", loaded: true }],
    }),
  );
  source.dispose();
});

it("replays an external edit that arrives while the selected view hydrates", async () => {
  const remote = new DeferredSourceRemote();
  const app = document("src/App.tsx", "typescriptreact");
  remote.setProject("react", [app]);
  const initial = remote.deferRead("react", app.path);
  const source = controller(remote);
  const starting = source.start();
  await vi.waitFor(() => expect(remote.reads).toEqual(["react:src/App.tsx"]));
  remote.files.set("react:src/App.tsx", {
    content: "current source",
    revision: "revision:current",
  });

  source.externalChanges([{ path: app.path, revision: "revision:current" }]);
  initial.resolve({ content: "stale source", revision: "revision:stale" });
  await starting;

  await vi.waitFor(() =>
    expect(source.getSnapshot().documents[0]).toMatchObject({
      path: app.path,
      content: "current source",
      loaded: true,
    }),
  );
  expect(remote.reads).toEqual(["react:src/App.tsx", "react:src/App.tsx"]);
  source.dispose();
});

it("retries a failed hydration when its repair event is already pending", async () => {
  const remote = new DeferredSourceRemote();
  const app = document("src/App.tsx", "typescriptreact");
  remote.setProject("react", [app]);
  const initial = remote.deferRead("react", app.path);
  const source = controller(remote);
  const starting = source.start();
  await vi.waitFor(() => expect(remote.reads).toEqual(["react:src/App.tsx"]));
  remote.files.set("react:src/App.tsx", {
    content: "repaired source",
    revision: "revision:repaired",
  });

  source.externalChanges([{ path: app.path, revision: "revision:repaired" }]);
  initial.reject(new Error("initial read failed"));
  await starting;

  await vi.waitFor(() =>
    expect(source.getSnapshot()).toMatchObject({
      phase: "ready",
      view: "react",
      active: app.path,
      documents: [
        {
          path: app.path,
          content: "repaired source",
          loaded: true,
        },
      ],
      targetDiagnostic: undefined,
    }),
  );
  expect(remote.reads).toEqual(["react:src/App.tsx", "react:src/App.tsx"]);
  source.dispose();
});

it("commits only the newest project inspection with every coalesced file change", async () => {
  const remote = new MemorySourceRemote();
  const app = document("src/App.tsx", "typescriptreact");
  const theme = document("src/theme.css", "css");
  const config = document("vite.config.ts", "typescript", "read");
  remote.setProject("react", [app, theme]);
  const source = controller(remote);
  await source.start();
  source.activate(theme.path);
  await vi.waitFor(() => expect(remote.reads).toContain("react:src/theme.css"));

  remote.files.set("react:src/App.tsx", { content: "next app", revision: "revision:app:next" });
  remote.files.set("react:src/theme.css", {
    content: "next theme",
    revision: "revision:theme:next",
  });
  remote.files.set("react:vite.config.ts", {
    content: "next config",
    revision: "revision:config:next",
  });
  const older = deferred<ViewProject>();
  const newest = deferred<ViewProject>();
  const inspect = vi
    .spyOn(remote, "project")
    .mockImplementationOnce(() => older.promise)
    .mockImplementationOnce(() => newest.promise);

  source.externalChanges([{ path: app.path, revision: "revision:app:next" }]);
  source.externalChanges([{ path: theme.path, revision: "revision:theme:next" }]);
  await vi.waitFor(() => expect(inspect).toHaveBeenCalledTimes(2));

  newest.resolve(project("react", [theme, app, config]));
  await vi.waitFor(() => {
    const snapshot = source.getSnapshot();
    expect(snapshot.documents.map(({ path }) => path)).toEqual([
      "src/theme.css",
      "src/App.tsx",
      "vite.config.ts",
    ]);
    expect(snapshot.documents.find(({ path }) => path === app.path)?.content).toBe("next app");
    expect(snapshot.documents.find(({ path }) => path === theme.path)?.content).toBe("next theme");
  });
  older.resolve(project("react", [app, theme]));
  await Promise.resolve();
  await Promise.resolve();

  expect(source.getSnapshot().documents.map(({ path }) => path)).toEqual([
    "src/theme.css",
    "src/App.tsx",
    "vite.config.ts",
  ]);
  source.dispose();
});

it("does not start an old-view read after its source session is disposed", async () => {
  const remote = new DeferredSourceRemote();
  const index = document("src/index.html", "html");
  const block = document("src/block.css", "css");
  const replacement = document("src/new.html", "html");
  remote.setProject("react", [index, block]);
  remote.setProject("svelte", [document("src/App.svelte", "svelte")]);
  const source = controller(remote);
  await source.start();
  source.activate(block.path);
  await vi.waitFor(() => expect(remote.reads).toContain("react:src/block.css"));
  source.edit(block.path, "local draft");
  source.activate(index.path);

  remote.setProject("react", [document(block.path, block.language, "read"), replacement]);
  const retiredRead = remote.deferRead("react", block.path);
  source.externalChanges([]);
  await vi.waitFor(() =>
    expect(remote.reads.filter((read) => read === "react:src/block.css")).toHaveLength(2),
  );

  await selectSourceView(source, "svelte");
  retiredRead.resolve({ content: "disk block", revision: "revision:block:current" });
  await retiredRead.promise;
  await Promise.resolve();
  await Promise.resolve();

  expect(remote.reads).not.toContain("react:src/new.html");
  expect(source.getSnapshot().view).toBe("svelte");
  source.dispose();
});

it("retries retained changes when the newest inspection fails after an older success", async () => {
  const remote = new MemorySourceRemote();
  const app = document("src/App.tsx", "typescriptreact");
  const theme = document("src/theme.css", "css");
  const config = document("vite.config.ts", "typescript", "read");
  remote.setProject("react", [app, theme]);
  const source = controller(remote);
  await source.start();
  source.activate(theme.path);
  await vi.waitFor(() => expect(remote.reads).toContain("react:src/theme.css"));
  remote.files.set("react:src/App.tsx", { content: "retry app", revision: "revision:app:retry" });
  remote.files.set("react:src/theme.css", {
    content: "retry theme",
    revision: "revision:theme:retry",
  });
  remote.files.set("react:vite.config.ts", {
    content: "retry config",
    revision: "revision:config:retry",
  });
  remote.projects.set("react", project("react", [theme, app, config]));
  const older = deferred<ViewProject>();
  const newest = deferred<ViewProject>();
  const inspect = vi
    .spyOn(remote, "project")
    .mockImplementationOnce(() => older.promise)
    .mockImplementationOnce(() => newest.promise);

  source.externalChanges([{ path: app.path, revision: "revision:app:retry" }]);
  source.externalChanges([{ path: theme.path, revision: "revision:theme:retry" }]);
  await vi.waitFor(() => expect(inspect).toHaveBeenCalledTimes(2));
  newest.reject(new Error("Newest inspection failed"));
  older.resolve(project("react", [app, theme]));

  await vi.waitFor(() => expect(inspect).toHaveBeenCalledTimes(3));
  await vi.waitFor(() => {
    const snapshot = source.getSnapshot();
    expect(snapshot.documents.map(({ path }) => path)).toEqual([
      "src/theme.css",
      "src/App.tsx",
      "vite.config.ts",
    ]);
    expect(snapshot.documents.find(({ path }) => path === app.path)?.content).toBe("retry app");
    expect(snapshot.documents.find(({ path }) => path === theme.path)?.content).toBe("retry theme");
  });
  source.dispose();
});

it("marks build freshness unavailable until project reinspection recovers", async () => {
  const remote = new MemorySourceRemote();
  const app = document("src/App.tsx", "typescriptreact");
  remote.setProject("react", [app]);
  const current = remote.projects.get("react");
  if (!current) {
    throw new Error("Expected the react project fixture");
  }
  remote.projects.set("react", {
    ...current,
    build: {
      ...unbuiltView,
      phase: "published",
      project_revision: "sha256:project-current",
      artifact_revision: "sha256:artifact-current",
    },
    artifact: {
      profile: "development",
      input_id: "sha256:project-current",
      artifact_id: "sha256:artifact-current",
    },
  });
  const source = controller(remote);
  await source.start();
  expect(source.getSnapshot().inspection).toEqual({ phase: "ready" });
  const first = deferred<ViewProject>();
  const second = deferred<ViewProject>();
  const inspect = vi
    .spyOn(remote, "project")
    .mockImplementationOnce(() => first.promise)
    .mockImplementationOnce(() => second.promise);

  source.reconcile();

  expect(source.getSnapshot().inspection).toEqual({ phase: "checking" });
  first.reject(new Error("Inspection unavailable"));
  await vi.waitFor(() => expect(inspect).toHaveBeenCalledTimes(2));
  second.reject(new Error("Inspection unavailable"));
  await vi.waitFor(() =>
    expect(source.getSnapshot().inspection).toEqual({
      phase: "unavailable",
      message: "Inspection unavailable",
    }),
  );
  expect(source.getSnapshot().build?.phase).toBe("published");
  expect(source.getSnapshot().documents[0]?.state.phase).not.toBe("error");

  inspect.mockRestore();
  source.reconcile();
  await vi.waitFor(() => expect(source.getSnapshot().inspection).toEqual({ phase: "ready" }));
  source.dispose();
});

it("reconciles additions, removals, and provider order from the project catalog", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [document("src/App.tsx", "typescriptreact")]);
  const source = controller(remote);
  await source.start();
  remote.setProject("react", [
    document("src/theme.css", "css"),
    document("src/components/Card.tsx", "typescriptreact"),
  ]);

  source.externalChanges([
    { path: "src/App.tsx", revision: null },
    { path: "src/components/Card.tsx", revision: "revision:react:src/components/Card.tsx" },
  ]);

  await vi.waitFor(() =>
    expect(source.getSnapshot().documents.map(({ path }) => path)).toEqual([
      "src/theme.css",
      "src/components/Card.tsx",
    ]),
  );
  expect(source.getSnapshot().active).toBe("src/theme.css");
  source.dispose();
});

it("blocks a transition on an edit-to-read conflict until the author discards it", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [document("src/App.tsx", "typescriptreact")]);
  const source = controller(remote);
  await source.start();
  source.edit("src/App.tsx", "local draft");
  remote.setProject("react", [document("src/App.tsx", "typescriptreact", "read")]);

  source.externalChanges([]);

  await vi.waitFor(() =>
    expect(source.getSnapshot().documents[0]).toMatchObject({
      access: "read",
      state: { phase: "conflict", conflict: { kind: "read-only" } },
    }),
  );
  expect(await source.prepareViewChange()).toBe(false);
  expect(remote.writes).toEqual([]);
  source.useSavedVersion();
  expect(await source.prepareViewChange()).toBe(true);
  expect(source.hasPendingChanges).toBe(false);
  source.dispose();
});

it("keeps the selected view active when its source cannot be read", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [document("src/App.tsx", "typescriptreact")]);
  remote.setProject("svelte", [document("src/App.svelte", "svelte")]);
  remote.files.delete("svelte:src/App.svelte");
  const source = controller(remote);
  await source.start();
  source.selectView("svelte");
  await vi.waitFor(() =>
    expect(source.getSnapshot().targetDiagnostic).toMatchObject({
      view: "svelte",
      path: "src/App.svelte",
    }),
  );

  expect(remote.inspections).toEqual(["react", "svelte"]);
  expect(remote.reads).toEqual(["react:src/App.tsx", "svelte:src/App.svelte"]);
  expect(source.getSnapshot()).toMatchObject({
    view: "svelte",
    active: null,
    documents: [],
    targetDiagnostic: {
      view: "svelte",
      path: "src/App.svelte",
      message: "Missing source src/App.svelte",
    },
  });
  source.dispose();
});

it("opens the next readable catalog document when the persisted startup document fails", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [
    document("src/App.tsx", "typescriptreact"),
    document("src/theme.css", "css"),
    document("deno.lock", "json", "read"),
  ]);
  remote.files.delete("react:src/theme.css");
  globalThis.localStorage.setItem("source-controller-test:source:react", "src/theme.css");
  const source = controller(remote);

  await source.start();

  expect(remote.reads).toEqual(["react:src/theme.css", "react:deno.lock"]);
  expect(source.getSnapshot()).toMatchObject({
    view: "react",
    active: "deno.lock",
    documents: [
      { path: "src/App.tsx" },
      { path: "src/theme.css", state: { phase: "error" } },
      { path: "deno.lock", content: "source:react:deno.lock", loaded: true },
    ],
    targetDiagnostic: {
      view: "react",
      path: "src/theme.css",
      message: "Missing source src/theme.css",
    },
  });
  expect(globalThis.localStorage.getItem("source-controller-test:source:react")).toBe("deno.lock");
  source.dispose();
});

it("clears a persisted-tab diagnostic after that document recovers", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [
    document("src/App.tsx", "typescriptreact"),
    document("src/theme.css", "css"),
  ]);
  remote.files.delete("react:src/App.tsx");
  globalThis.localStorage.setItem("source-controller-test:source:react", "src/App.tsx");
  const source = controller(remote);
  await source.start();
  expect(source.getSnapshot().targetDiagnostic?.path).toBe("src/App.tsx");
  remote.files.set("react:src/App.tsx", { content: "recovered", revision: "revision:recovered" });

  source.activate("src/App.tsx");

  await vi.waitFor(() => expect(source.getSnapshot().targetDiagnostic).toBeUndefined());
  expect(source.getSnapshot().active).toBe("src/App.tsx");
  expect(source.getSnapshot().documents.find(({ path }) => path === "src/App.tsx")).toMatchObject({
    path: "src/App.tsx",
    content: "recovered",
    loaded: true,
  });
  source.dispose();
});

it("clears a persisted-tab diagnostic when the provider removes that document", async () => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [
    document("src/App.tsx", "typescriptreact"),
    document("src/theme.css", "css"),
  ]);
  remote.files.delete("react:src/App.tsx");
  globalThis.localStorage.setItem("source-controller-test:source:react", "src/App.tsx");
  const source = controller(remote);
  await source.start();
  expect(source.getSnapshot().targetDiagnostic?.path).toBe("src/App.tsx");
  remote.setProject("react", [document("src/theme.css", "css")]);

  source.externalChanges([]);

  await vi.waitFor(() => expect(source.getSnapshot().targetDiagnostic).toBeUndefined());
  expect(source.getSnapshot().documents.map(({ path }) => path)).toEqual(["src/theme.css"]);
  source.dispose();
});

it.each([
  {
    name: "source deletion",
    nextDocuments: [document("src/theme.css", "css")],
    changes: [{ path: "src/App.tsx", revision: null }],
    provider: "test/react",
  },
  {
    name: "provider rebind",
    nextDocuments: [document("src/App.svelte", "svelte")],
    changes: [],
    provider: "test/svelte",
  },
])("makes a dirty document orphaned after $name", async ({ nextDocuments, changes, provider }) => {
  const remote = new MemorySourceRemote();
  remote.setProject("react", [document("src/App.tsx", "typescriptreact")]);
  const source = controller(remote);
  await source.start();
  source.edit("src/App.tsx", "local draft");
  remote.setProject("react", nextDocuments, provider);

  source.externalChanges(changes);

  await vi.waitFor(() =>
    expect(source.getSnapshot().documents.find(({ path }) => path === "src/App.tsx")).toMatchObject(
      {
        access: "read",
        state: {
          phase: "conflict",
          conflict: {
            kind: "orphan",
            local: "local draft",
            remote: {
              content: "source:react:src/App.tsx",
              revision: "revision:react:src/App.tsx",
            },
          },
        },
      },
    ),
  );
  expect(remote.writes).toEqual([]);
  expect(await source.prepareViewChange()).toBe(false);

  source.useSavedVersion();

  expect(source.getSnapshot().documents.map(({ path }) => path)).toEqual(
    nextDocuments.map(({ path }) => path),
  );
  expect(source.getSnapshot().active).toBe(nextDocuments[0]?.path);
  expect(source.getSnapshot().provider).toBe(provider);
  expect(await source.prepareViewChange()).toBe(true);
  expect(remote.writes).toEqual([]);
  source.dispose();
});
