import type { SourceDocumentPath } from "@marimo-studio/protocol/source-documents";
import type { ViewProject } from "@marimo-studio/protocol/view-project";

import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  type RemoteSource,
  RevisionConflict,
  type SourceRemote,
} from "../src/features/source-editor/remote.ts";
import {
  type SourceObserver,
  type SourceState,
  SyncedSource,
} from "../src/features/source-editor/sync.ts";
import { unbuiltView, viewOwner } from "./fixtures.ts";

class MemoryRemote implements SourceRemote {
  source: RemoteSource = { content: "initial", revision: "r1" };
  conflict = false;
  readError: Error | undefined;
  lastWriteOwner: { catalogGeneration: string; viewGeneration: string } | undefined;

  project(view: string): Promise<ViewProject> {
    return Promise.resolve({
      schema: 1,
      ...viewOwner,
      view,
      provider: "test/provider",
      provider_options: {},
      documents: [],
      mounts: [],
      diagnostics: [],
      build: unbuiltView,
      artifact: null,
    });
  }

  read(): Promise<RemoteSource> {
    if (this.readError) {
      return Promise.reject(this.readError);
    }
    return Promise.resolve({ ...this.source });
  }

  write(
    _view: string,
    _path: SourceDocumentPath,
    content: string,
    revision: string,
    catalogGeneration: string,
    viewGeneration: string,
  ): Promise<string> {
    this.lastWriteOwner = { catalogGeneration, viewGeneration };
    if (this.conflict || revision !== this.source.revision) {
      return Promise.reject(new RevisionConflict(this.source.revision));
    }
    this.source = { content, revision: `${revision}-next` };
    return Promise.resolve(this.source.revision);
  }
}

test("a source read can replace the owner used by its next write", async () => {
  const remote = new MemoryRemote();
  remote.source = {
    content: "repairable",
    revision: "r1",
    catalogGeneration: "a".repeat(64),
    viewGeneration: "b".repeat(64),
  };
  const result = observed();
  const source = new SyncedSource(editable("view.toml"), remote, result.observer, 60_000);
  source.setOwner("c".repeat(64), "d".repeat(64));

  await source.load("dashboard");
  source.edit("repaired");
  await source.save();

  assert.deepEqual(remote.lastWriteOwner, {
    catalogGeneration: "a".repeat(64),
    viewGeneration: "b".repeat(64),
  });
});

interface PendingWrite {
  content: string;
  revision: string;
  resolve(revision: string): void;
  reject(error: Error): void;
}

class DeferredRemote extends MemoryRemote {
  writes: PendingWrite[] = [];

  override write(
    _view: string,
    _path: SourceDocumentPath,
    content: string,
    revision: string,
  ): Promise<string> {
    return new Promise((resolve, reject) => {
      this.writes.push({ content, revision, resolve, reject });
    });
  }
}

class DeferredReadRemote extends MemoryRemote {
  reads: Array<{
    resolve(source: RemoteSource): void;
    reject(error: Error): void;
  }> = [];

  override read(): Promise<RemoteSource> {
    return new Promise((resolve, reject) => {
      this.reads.push({ resolve, reject });
    });
  }
}

class DeferredWriteReadRemote extends DeferredRemote {
  reads: Array<{
    resolve(source: RemoteSource): void;
    reject(error: Error): void;
  }> = [];

  override read(): Promise<RemoteSource> {
    return new Promise((resolve, reject) => {
      this.reads.push({ resolve, reject });
    });
  }
}

const observed = () => {
  const documents: string[] = [];
  const states: SourceState[] = [];
  const observer: SourceObserver = {
    document(_name, content) {
      documents.push(content);
    },
    state(state) {
      states.push(state);
    },
  };
  return { documents, states, observer };
};

const editable = (path: SourceDocumentPath) => ({
  path,
  language: "text",
  access: "edit" as const,
});

test("read-only documents never create pending writes", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource(
    { path: "deno.lock", language: "json", access: "read" },
    remote,
    result.observer,
    1,
  );
  await source.load("dashboard");

  source.edit("changed");

  assert.equal(await source.save(), true);
  assert.equal(source.hasPendingChanges, false);
  assert.equal(remote.source.content, "initial");
});

test("an access change preserves dirty edits as a discardable read-only conflict", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("local draft");
  remote.source = { content: "current disk", revision: "r2" };

  await source.updateDocument({ path: "src/App.tsx", language: "typescriptreact", access: "read" });

  assert.equal(source.access, "read");
  assert.equal(await source.save(), false);
  assert.deepEqual(result.states.at(-1)?.conflict, {
    kind: "read-only",
    local: "local draft",
    remote: { content: "current disk", revision: "r2" },
  });
  remote.source = { content: "newer disk", revision: "r3" };
  await source.reconcile();
  assert.deepEqual(result.states.at(-1)?.conflict, {
    kind: "read-only",
    local: "local draft",
    remote: { content: "newer disk", revision: "r3" },
  });
  source.useSavedVersion();
  assert.equal(source.hasPendingChanges, false);
  assert.equal(await source.save(), true);
  assert.equal(result.documents.at(-1), "newer disk");
});

test("an access change reads disk after its active write settles", async () => {
  const remote = new DeferredWriteReadRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  source.open("dashboard", { content: "initial", revision: "r1" });
  source.edit("saved before access change");
  const saving = source.save();

  const transition = source.updateDocument({
    path: "src/App.tsx",
    language: "typescriptreact",
    access: "read",
  });

  assert.equal(remote.reads.length, 0);
  remote.source = { content: "saved before access change", revision: "r2" };
  remote.writes[0].resolve("r2");
  assert.equal(await saving, true);
  await Promise.resolve();
  assert.equal(remote.reads.length, 1);
  remote.reads[0].resolve(remote.source);
  await transition;

  assert.equal(source.access, "read");
  assert.equal(source.hasPendingChanges, false);
  assert.equal(result.documents.at(-1), "saved before access change");
});

test("a disposed access change cannot read after its active write settles", async () => {
  const remote = new DeferredWriteReadRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  source.open("dashboard", { content: "initial", revision: "r1" });
  source.edit("write in flight");
  const saving = source.save();
  const transition = source.updateDocument({
    path: "src/App.tsx",
    language: "typescriptreact",
    access: "read",
  });

  assert.equal(remote.reads.length, 0);
  source.dispose();
  remote.writes[0].resolve("r2");

  assert.equal(await saving, false);
  await transition;
  assert.equal(remote.reads.length, 0);
});

test("an orphan conflict retains the latest saved disk source and prevents another write", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("saved edit");
  assert.equal(await source.save(), true);
  source.edit("orphaned draft");

  assert.equal(await source.orphan(), true);

  assert.deepEqual(result.states.at(-1)?.conflict, {
    kind: "orphan",
    local: "orphaned draft",
    remote: { content: "saved edit", revision: "r1-next" },
  });
  assert.equal(await source.save(), false);
  assert.deepEqual(remote.source, { content: "saved edit", revision: "r1-next" });
});

test("orphaning cannot read stale disk before its active write settles", async () => {
  const remote = new DeferredWriteReadRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  source.open("dashboard", { content: "initial", revision: "r1" });
  source.edit("write in flight");
  const saving = source.save();
  source.edit("unsaved orphan draft");

  const orphaning = source.orphan();

  assert.equal(remote.reads.length, 0);
  remote.source = { content: "write in flight", revision: "r2" };
  remote.writes[0].resolve("r2");
  assert.equal(await saving, false);
  await Promise.resolve();
  assert.equal(remote.reads.length, 1);
  remote.reads[0].resolve(remote.source);

  assert.equal(await orphaning, true);
  assert.deepEqual(result.states.at(-1)?.conflict, {
    kind: "orphan",
    local: "unsaved orphan draft",
    remote: { content: "write in flight", revision: "r2" },
  });
  assert.equal(remote.writes.length, 1);
});

test("a clean external edit replaces the loaded source", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 1);
  await source.load("dashboard");
  remote.source = { content: "agent edit", revision: "r2" };

  await source.externalChange("r2");

  assert.deepEqual(result.documents, ["", "initial", "agent edit"]);
  assert.deepEqual(result.states.at(-1)?.phase, "external");
});

test("the latest reconciliation wins across completion orders and stale failures", async () => {
  const remote = new DeferredReadRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 1);
  source.open("dashboard", { content: "initial", revision: "r0" });

  const lateOlder = source.reconcile();
  const earlyNewer = source.reconcile();
  remote.reads[1].resolve({ content: "newest", revision: "r2" });
  await earlyNewer;
  remote.reads[0].resolve({ content: "older", revision: "r1" });
  await lateOlder;

  assert.deepEqual(result.documents.at(-1), "newest");
  assert.deepEqual(result.states.at(-1)?.phase, "external");

  const earlyOlder = source.reconcile();
  const lateNewer = source.reconcile();
  remote.reads[2].resolve({ content: "ignored", revision: "r3" });
  await earlyOlder;

  assert.deepEqual(result.documents.at(-1), "newest");

  remote.reads[3].resolve({ content: "current", revision: "r4" });
  await lateNewer;

  assert.deepEqual(result.documents.at(-1), "current");
  assert.deepEqual(result.states.at(-1)?.phase, "external");

  const failingOlder = source.reconcile();
  const successfulNewer = source.reconcile();
  remote.reads[5].resolve({ content: "final", revision: "r6" });
  await successfulNewer;
  remote.reads[4].reject(new Error("stale request failed"));
  await failingOlder;

  assert.deepEqual(result.documents.at(-1), "final");
  assert.deepEqual(result.states.at(-1)?.phase, "external");
});

test("a delayed initial load cannot replace a newer reconciliation", async () => {
  const remote = new DeferredReadRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 1);

  const loading = source.load("dashboard");
  const reconciling = source.reconcile();
  remote.reads[1].resolve({ content: "newest", revision: "r2" });
  await reconciling;
  remote.reads[0].resolve({ content: "older", revision: "r1" });

  assert.equal(await loading, false);
  assert.equal(source.currentRevision, "r2");
  assert.deepEqual(result.documents.at(-1), "newest");
  assert.deepEqual(result.states.at(-1)?.phase, "external");
});

test("a stale reconciliation cannot replace the current conflict", async () => {
  const remote = new DeferredReadRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  source.open("dashboard", { content: "initial", revision: "r0" });
  source.edit("local edit");

  const older = source.reconcile();
  const newer = source.reconcile();
  remote.reads[1].resolve({ content: "current disk", revision: "r2" });
  await newer;
  remote.reads[0].resolve({ content: "stale disk", revision: "r1" });
  await older;

  assert.deepEqual(result.states.at(-1)?.conflict, {
    kind: "revision",
    local: "local edit",
    remote: { content: "current disk", revision: "r2" },
  });
});

test("a stale conflict read cannot replace a newer reconciliation", async () => {
  const remote = new DeferredReadRemote();
  remote.conflict = true;
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  source.open("dashboard", { content: "initial", revision: "r0" });
  source.edit("local edit");

  const saving = source.save();
  await Promise.resolve();
  const reconciliation = source.reconcile();
  remote.reads[1].resolve({ content: "current disk", revision: "r3" });
  await reconciliation;
  remote.reads[0].resolve({ content: "stale disk", revision: "r2" });
  await saving;

  assert.deepEqual(result.states.at(-1)?.conflict, {
    kind: "revision",
    local: "local edit",
    remote: { content: "current disk", revision: "r3" },
  });
});

test("a failed view load never displays source from the previous view", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 1);
  await source.load("dashboard");
  remote.readError = new Error("missing source");

  await source.load("executive");

  assert.deepEqual(result.documents.at(-1), "");
  assert.deepEqual(result.states.at(-1)?.phase, "error");
});

test("an edit made during the initial read is preserved as a conflict", async () => {
  const remote = new DeferredReadRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);

  const loading = source.load("dashboard");
  source.edit("local draft");
  remote.reads[0].resolve({ content: "disk source", revision: "r1" });

  assert.equal(await loading, false);
  assert.equal(source.hasPendingChanges, true);
  assert.deepEqual(result.states.at(-1), {
    path: "src/App.tsx",
    phase: "conflict",
    conflict: {
      kind: "revision",
      local: "local draft",
      remote: { content: "disk source", revision: "r1" },
    },
    message: undefined,
  });
});

test("source conflicts accept explicit disk and local resolutions", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("local edit");
  remote.source = { content: "agent edit", revision: "r2" };

  await source.externalChange("r2");

  assert.deepEqual(result.states.at(-1)?.phase, "conflict");
  assert.deepEqual(result.states.at(-1)?.conflict, {
    kind: "revision",
    local: "local edit",
    remote: { content: "agent edit", revision: "r2" },
  });
  source.useSavedVersion();
  assert.deepEqual(result.documents.at(-1), "agent edit");

  source.edit("second local edit");
  remote.source = { content: "second agent edit", revision: "r3" };
  await source.externalChange("r3");

  const saved = await source.overwriteSavedVersion();

  assert.deepEqual(saved, true);
  assert.deepEqual(remote.source.content, "second local edit");
  assert.deepEqual(result.states.at(-1)?.phase, "saved");
});

test("a disposed local resolution cannot start another write", async () => {
  const remote = new DeferredWriteReadRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  source.open("dashboard", { content: "initial", revision: "r1" });
  source.edit("local edit");
  const saving = source.save();
  const conflicting = source.reconcile();
  remote.reads[0].resolve({ content: "disk edit", revision: "r2" });
  await conflicting;

  const resolution = source.overwriteSavedVersion();
  source.dispose();
  remote.writes[0].resolve("r3");

  assert.equal(await saving, false);
  assert.equal(await resolution, false);
  assert.equal(remote.writes.length, 1);
});

test("local conflict resolution waits for the failed write to settle", async () => {
  const remote = new MemoryRemote();
  remote.conflict = true;
  const result = observed();
  let source!: SyncedSource;
  let resolution: Promise<boolean> | undefined;
  const observer: SourceObserver = {
    document: result.observer.document,
    state(state) {
      result.observer.state(state);
      if (state.phase === "conflict") {
        remote.conflict = false;
        resolution = source.overwriteSavedVersion();
      }
    },
  };
  source = new SyncedSource(editable("src/App.tsx"), remote, observer, 60_000);
  await source.load("dashboard");
  source.edit("local edit");
  remote.source = { content: "disk edit", revision: "r2" };

  const conflicted = await source.save();

  assert.equal(conflicted, false);
  assert.equal(await resolution, true);
  assert.deepEqual(remote.source.content, "local edit");
  assert.deepEqual(result.states.at(-1)?.phase, "saved");
});

test("matching disk content clears an existing conflict", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("local edit");
  remote.source = { content: "other edit", revision: "r2" };
  await source.externalChange("r2");

  remote.source = { content: "local edit", revision: "r3" };
  await source.externalChange("r3");

  assert.equal(source.hasConflict, false);
  assert.equal(source.hasPendingChanges, false);
  assert.equal(await source.save(), true);
  assert.equal(result.states.at(-1)?.phase, "saved");
});

test("active saves absorb filesystem events and flush later edits in revision order", async () => {
  const remote = new DeferredRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("first edit");

  const autosave = source.save();
  source.edit("latest edit");
  const flush = source.save();
  remote.source = { content: "first edit", revision: "r2" };

  assert.deepEqual(remote.writes.length, 1);
  assert.deepEqual(remote.writes[0].content, "first edit");
  await source.externalChange("r2");
  remote.writes[0].resolve("r2");
  await Promise.resolve();
  assert.deepEqual(remote.writes.length, 2);
  assert.deepEqual(remote.writes[1].content, "latest edit");
  assert.deepEqual(remote.writes[1].revision, "r2");
  remote.writes[1].resolve("r3");

  assert.deepEqual(await autosave, true);
  assert.deepEqual(await flush, true);
  assert.deepEqual(source.hasConflict, false);
  assert.deepEqual(source.hasPendingChanges, false);
});

test("a late write response preserves a newer external conflict", async () => {
  const remote = new DeferredRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("local edit");
  const saving = source.save();
  remote.source = { content: "newer disk edit", revision: "r3" };

  await source.externalChange("r3");
  remote.writes[0].resolve("r2");

  assert.equal(await saving, false);
  assert.deepEqual(result.states.at(-1)?.conflict, {
    kind: "revision",
    local: "local edit",
    remote: { content: "newer disk edit", revision: "r3" },
  });
  assert.equal(source.hasPendingChanges, true);
});

test("a late write response preserves an external deletion", async () => {
  const remote = new DeferredRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("local edit");
  const saving = source.save();

  await source.externalChange(null);
  remote.writes[0].resolve("r2");

  assert.equal(await saving, false);
  assert.equal(source.hasPendingChanges, true);
  assert.deepEqual(result.states.at(-1)?.phase, "error");
  assert.deepEqual(
    result.states.at(-1)?.message,
    "src/App.tsx was deleted on disk. Restore it before saving in Studio.",
  );
});

test("a conflict keeps the latest editor text", async () => {
  const remote = new DeferredRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("older edit");
  const saving = source.save();
  source.edit("latest edit");
  remote.source = { content: "disk edit", revision: "r2" };
  remote.writes[0].reject(new RevisionConflict("r2", "/workspace/recovered-App.tsx"));

  assert.deepEqual(await saving, false);
  assert.deepEqual(result.states.at(-1)?.conflict, {
    kind: "revision",
    local: "latest edit",
    remote: { content: "disk edit", revision: "r2" },
    externalRecovery: "/workspace/recovered-App.tsx",
  });
});

test("dirty text without a loaded revision cannot be discarded", async () => {
  const remote = new MemoryRemote();
  remote.readError = new Error("source unavailable");
  const result = observed();
  const source = new SyncedSource(editable("src/App.tsx"), remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("recovered locally");

  assert.deepEqual(await source.save(), false);
  assert.deepEqual(source.hasPendingChanges, true);
  assert.deepEqual(result.states.at(-1)?.phase, "error");
});

test("an external deletion survives a cancelled staged load", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource(editable("src/app.css"), remote, result.observer, 60_000);
  await source.load("dashboard");

  await source.externalChange(null);

  assert.deepEqual(result.documents.at(-1), "");
  assert.deepEqual(result.states.at(-1)?.phase, "error");
  assert.deepEqual(
    result.states.at(-1)?.message,
    "src/app.css was deleted on disk. Restore it before saving in Studio.",
  );

  source.beginLoad();
  source.cancelLoad();

  assert.deepEqual(result.states.at(-1)?.phase, "error");
  assert.deepEqual(
    result.states.at(-1)?.message,
    "src/app.css was deleted on disk. Restore it before saving in Studio.",
  );
});
