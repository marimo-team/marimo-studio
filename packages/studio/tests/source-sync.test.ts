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

test("the latest reconciliation wins across completion orders and stale failures", async () => {
  const remote = new DeferredReadRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 1);
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

test("an edit made during the initial read is preserved as a conflict", async () => {
  const remote = new DeferredReadRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 60_000);

  const loading = source.load("dashboard");
  source.edit("local draft");
  remote.reads[0].resolve({ content: "disk source", revision: "r1" });

  assert.equal(await loading, false);
  assert.equal(source.hasPendingChanges, true);
  assert.deepEqual(result.states.at(-1), {
    name: "index.html",
    phase: "conflict",
    conflict: {
      local: "local draft",
      remote: { content: "disk source", revision: "r1" },
    },
    message: undefined,
  });
});

test("source conflicts accept explicit disk and local resolutions", async () => {
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

  source.edit("second local edit");
  remote.source = { content: "second agent edit", revision: "r3" };
  await source.externalChange("r3");

  const saved = await source.keepLocal();

  assert.deepEqual(saved, true);
  assert.deepEqual(remote.source.content, "second local edit");
  assert.deepEqual(result.states.at(-1)?.phase, "saved");
});

test("active saves absorb filesystem events and flush later edits in revision order", async () => {
  const remote = new DeferredRemote();
  const result = observed();
  const source = new SyncedSource("index.html", remote, result.observer, 60_000);
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

test("an external deletion survives a cancelled staged load", async () => {
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

  source.beginLoad();
  source.cancelLoad();

  assert.deepEqual(result.states.at(-1)?.phase, "error");
  assert.deepEqual(
    result.states.at(-1)?.message,
    "app.css was deleted on disk. Restore it before saving in Studio.",
  );
});
