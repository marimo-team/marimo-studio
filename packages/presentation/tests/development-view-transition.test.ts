import assert from "node:assert/strict";
import { test, vi } from "vite-plus/test";

import type { DocumentRevisionCommit } from "../src/document/revision-document.ts";

import { DevelopmentViewTransition } from "../src/document/development-view-transition.ts";

const commit = (supportChanged = false): DocumentRevisionCommit => ({
  target: { documentUrl: "/report/", supportUrl: "/support/report" },
  supportChanged,
  reloadDocument: false,
});

const deferred = <Value>() => {
  let resolve!: (value: Value) => void;
  const promise = new Promise<Value>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

test("a canceled standalone transition reconnects its current event stream", async () => {
  const closeEvents = vi.fn();
  const connectEvents = vi.fn();
  const transition = new DevelopmentViewTransition({
    embedded: false,
    closeEvents,
    connectEvents,
    replaceView: vi.fn(async () => undefined),
  });

  await transition.run("/report/", "/support/report");

  assert.equal(closeEvents.mock.calls.length, 1);
  assert.equal(connectEvents.mock.calls.length, 1);
});

test("an embedded transition leaves event ownership with Studio", async () => {
  const closeEvents = vi.fn();
  const connectEvents = vi.fn();
  const transition = new DevelopmentViewTransition({
    embedded: true,
    closeEvents,
    connectEvents,
    replaceView: vi.fn(async () => undefined),
  });

  await transition.run("/report/", "/support/report");

  assert.equal(closeEvents.mock.calls.length, 0);
  assert.equal(connectEvents.mock.calls.length, 0);
});

test("an invalidated transition cannot reconnect its event stream", async () => {
  const pending = deferred<DocumentRevisionCommit | undefined>();
  const connectEvents = vi.fn();
  const transition = new DevelopmentViewTransition({
    embedded: false,
    closeEvents: vi.fn(),
    connectEvents,
    replaceView: vi.fn(() => pending.promise),
  });

  const running = transition.run("/report/", "/support/report");
  transition.cancel();
  pending.resolve(undefined);
  await running;

  assert.equal(connectEvents.mock.calls.length, 0);
});

test("a committed support change owns its event stream reconnect", async () => {
  const connectEvents = vi.fn();
  const transition = new DevelopmentViewTransition({
    embedded: false,
    closeEvents: vi.fn(),
    connectEvents,
    replaceView: vi.fn(async () => commit(true)),
  });

  await transition.run("/report/", "/support/report");

  assert.equal(connectEvents.mock.calls.length, 0);
});
