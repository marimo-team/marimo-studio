import type { SourceName } from "@marimo-studio/protocol/source-events";

import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { type RemoteSource, RevisionConflict, type SourceRemote } from "../src/source/remote.ts";
import { type SourceObserver, type SourceState, SyncedSource } from "../src/source/sync.ts";

class MemoryRemote implements SourceRemote {
  source: RemoteSource = { content: "initial", revision: "r1" };
  conflict = false;
  readError: Error | undefined;

  read(): Promise<RemoteSource> {
    if (this.readError) {
      return Promise.reject(this.readError);
    }
    return Promise.resolve({ ...this.source });
  }

  write(_view: string, _name: SourceName, content: string, revision: string): Promise<string> {
    if (this.conflict || revision !== this.source.revision) {
      return Promise.reject(new RevisionConflict(this.source.revision));
    }
    this.source = { content, revision: `${revision}-next` };
    return Promise.resolve(this.source.revision);
  }
}

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
    _name: SourceName,
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

test("a clean external edit replaces the loaded source", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 1);
  await source.load("dashboard");
  remote.source = { content: "agent edit", revision: "r2" };

  await source.externalChange("r2");

  assert.deepEqual(result.documents, ["", "initial", "agent edit"]);
  assert.deepEqual(result.states.at(-1)?.phase, "external");
});

test("an older reconciliation cannot replace a newer result", async () => {
  const remote = new DeferredReadRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 1);
  source.open("dashboard", { content: "initial", revision: "r0" });

  const older = source.reconcile();
  const newer = source.reconcile();
  remote.reads[1].resolve({ content: "newest", revision: "r2" });
  await newer;
  remote.reads[0].resolve({ content: "older", revision: "r1" });
  await older;

  assert.deepEqual(result.documents.at(-1), "newest");
  assert.deepEqual(result.states.at(-1)?.phase, "external");
});

test("the newest reconciliation applies after an older read finishes", async () => {
  const remote = new DeferredReadRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 1);
  source.open("dashboard", { content: "initial", revision: "r0" });

  const older = source.reconcile();
  const newer = source.reconcile();
  remote.reads[0].resolve({ content: "older", revision: "r1" });
  await older;
  remote.reads[1].resolve({ content: "newest", revision: "r2" });
  await newer;

  assert.deepEqual(result.documents.at(-1), "newest");
  assert.deepEqual(result.states.at(-1)?.phase, "external");
});

test("a stale read failure cannot replace a newer result", async () => {
  const remote = new DeferredReadRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 1);
  source.open("dashboard", { content: "initial", revision: "r0" });

  const older = source.reconcile();
  const newer = source.reconcile();
  remote.reads[1].resolve({ content: "newest", revision: "r2" });
  await newer;
  remote.reads[0].reject(new Error("stale request failed"));
  await older;

  assert.deepEqual(result.documents.at(-1), "newest");
  assert.deepEqual(result.states.at(-1)?.phase, "external");
});

test("a stale reconciliation cannot replace the current conflict", async () => {
  const remote = new DeferredReadRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 60_000);
  source.open("dashboard", { content: "initial", revision: "r0" });
  source.edit("local edit");

  const older = source.reconcile();
  const newer = source.reconcile();
  remote.reads[1].resolve({ content: "current disk", revision: "r2" });
  await newer;
  remote.reads[0].resolve({ content: "stale disk", revision: "r1" });
  await older;

  assert.deepEqual(result.states.at(-1)?.conflict, {
    local: "local edit",
    remote: { content: "current disk", revision: "r2" },
  });
});

test("a stale conflict read cannot replace a newer reconciliation", async () => {
  const remote = new DeferredReadRemote();
  remote.conflict = true;
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 60_000);
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
    local: "local edit",
    remote: { content: "current disk", revision: "r3" },
  });
});

test("a failed view load never displays source from the previous view", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 1);
  await source.load("dashboard");
  remote.readError = new Error("missing source");

  await source.load("executive");

  assert.deepEqual(result.documents.at(-1), "");
  assert.deepEqual(result.states.at(-1)?.phase, "error");
});

test("concurrent local and disk edits require an explicit resolution", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("local edit");
  remote.source = { content: "agent edit", revision: "r2" };

  await source.externalChange("r2");

  assert.deepEqual(result.states.at(-1)?.phase, "conflict");
  assert.deepEqual(result.states.at(-1)?.conflict, {
    local: "local edit",
    remote: { content: "agent edit", revision: "r2" },
  });
  source.useDisk();
  assert.deepEqual(result.documents.at(-1), "agent edit");
});

test("keep mine writes against the latest disk revision", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource("app.css", remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("body { color: red; }");
  remote.source = { content: "body {}", revision: "r2" };
  await source.externalChange("r2");

  const saved = await source.keepLocal();

  assert.deepEqual(saved, true);
  assert.deepEqual(remote.source.content, "body { color: red; }");
  assert.deepEqual(result.states.at(-1)?.phase, "saved");
});

test("edits made during a save are written in revision order", async () => {
  const remote = new DeferredRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("first edit");

  const autosave = source.save();
  source.edit("latest edit");
  const flush = source.save();

  assert.deepEqual(remote.writes.length, 1);
  assert.deepEqual(remote.writes[0].content, "first edit");
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

test("a conflict keeps the latest editor text", async () => {
  const remote = new DeferredRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("older edit");
  const saving = source.save();
  source.edit("latest edit");
  remote.source = { content: "disk edit", revision: "r2" };
  remote.writes[0].reject(new RevisionConflict("r2"));

  assert.deepEqual(await saving, false);
  assert.deepEqual(result.states.at(-1)?.conflict, {
    local: "latest edit",
    remote: { content: "disk edit", revision: "r2" },
  });
});

test("dirty text without a loaded revision cannot be discarded", async () => {
  const remote = new MemoryRemote();
  remote.readError = new Error("source unavailable");
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("recovered locally");

  assert.deepEqual(await source.save(), false);
  assert.deepEqual(source.hasPendingChanges, true);
  assert.deepEqual(result.states.at(-1)?.phase, "error");
});

test("an external deletion clears clean source and reports repair", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource("app.css", remote, result.observer, 60_000);
  await source.load("dashboard");

  await source.externalChange(null);

  assert.deepEqual(result.documents.at(-1), "");
  assert.deepEqual(result.states.at(-1)?.phase, "error");
  assert.deepEqual(
    result.states.at(-1)?.message,
    "app.css was deleted on disk. Restore it before saving in Studio.",
  );
});

test("cancelling a staged load preserves a missing-source error", async () => {
  const remote = new MemoryRemote();
  const result = observed();
  const source = new SyncedSource("app.css", remote, result.observer, 60_000);
  await source.load("dashboard");
  await source.externalChange(null);

  source.beginLoad();
  source.cancelLoad();

  assert.deepEqual(result.states.at(-1)?.phase, "error");
  assert.deepEqual(
    result.states.at(-1)?.message,
    "app.css was deleted on disk. Restore it before saving in Studio.",
  );
});

test("the filesystem event for an active save is not a conflict", async () => {
  const remote = new DeferredRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 60_000);
  await source.load("dashboard");
  source.edit("saved content");
  const saving = source.save();
  source.edit("newer content");
  remote.source = { content: "saved content", revision: "r2" };

  await source.externalChange("r2");
  remote.writes[0].resolve("r2");
  await Promise.resolve();
  assert.deepEqual(remote.writes[1].content, "newer content");
  assert.deepEqual(remote.writes[1].revision, "r2");
  remote.writes[1].resolve("r3");

  assert.deepEqual(await saving, true);
  assert.deepEqual(source.hasConflict, false);
  assert.deepEqual(source.hasPendingChanges, false);
});
