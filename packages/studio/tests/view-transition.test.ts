import assert from "node:assert/strict";
import { test, vi } from "vite-plus/test";

import { ViewTransition } from "../src/features/views/transition.ts";

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

test("the latest view request is the only transition committed", async () => {
  const loads = new Map<string, ReturnType<typeof deferred<boolean>>>();
  const committed: Array<[string, string, boolean]> = [];
  const transition = new ViewTransition("dashboard", {
    prepare(view) {
      const load = deferred<boolean>();
      loads.set(view, load);
      return load.promise;
    },
    commit(view, landing, changed) {
      committed.push([view, landing, changed]);
      return true;
    },
    cancel() {},
  });

  const first = transition.select("operations", "develop");
  const second = transition.select("executive", "preserve");
  loads.get("executive")!.resolve(true);
  assert.deepEqual(await second, true);
  loads.get("operations")!.resolve(true);
  assert.deepEqual(await first, false);

  assert.deepEqual(committed, [["executive", "preserve", true]]);
});

test("choosing the current view cancels a pending transition", async () => {
  const pending = deferred<boolean>();
  const committed: Array<[string, string, boolean]> = [];
  let cancellations = 0;
  const transition = new ViewTransition("dashboard", {
    prepare(view) {
      return view === "dashboard" ? Promise.resolve(true) : pending.promise;
    },
    commit(view, landing, changed) {
      committed.push([view, landing, changed]);
      return true;
    },
    cancel() {
      cancellations += 1;
    },
  });

  const switching = transition.select("operations", "preserve");
  assert.deepEqual(await transition.select("dashboard", "develop"), true);
  pending.resolve(true);

  assert.deepEqual(await switching, false);
  assert.deepEqual(cancellations, 1);
  assert.deepEqual(committed, [["dashboard", "develop", false]]);
});

test("commits navigation intent only after target preparation succeeds", async () => {
  const committed: unknown[][] = [];
  const transition = new ViewTransition("dashboard", {
    prepare: async (view) => view === "report",
    commit(...args) {
      committed.push(args);
      return true;
    },
    cancel() {},
  });
  const intent = { query: "?region=apac", hash: "#details" };

  assert.equal(await transition.select("broken", "preserve", intent), false);
  assert.deepEqual(committed, []);
  assert.equal(await transition.select("report", "preserve", intent), true);
  assert.deepEqual(committed, [["report", "preserve", true, intent]]);
});

test("prepares same-view navigation before committing it", async () => {
  const committed: unknown[][] = [];
  const prepared: unknown[][] = [];
  const transition = new ViewTransition("dashboard", {
    prepare(...args) {
      prepared.push(args);
      return Promise.resolve(false);
    },
    commit(...args) {
      committed.push(args);
      return true;
    },
    cancel() {},
  });
  const intent = { query: "?region=apac", hash: "#details" };

  assert.equal(await transition.select("dashboard", "preserve", intent), false);
  assert.deepEqual(prepared, [["dashboard", false, intent]]);
  assert.deepEqual(committed, []);
});

test("commits only the newest same-view navigation", async () => {
  const first = deferred<boolean>();
  const second = deferred<boolean>();
  const committed: unknown[][] = [];
  const transition = new ViewTransition("dashboard", {
    prepare(_view, _changed, navigation) {
      return navigation?.hash === "#first" ? first.promise : second.promise;
    },
    commit(...args) {
      committed.push(args);
      return true;
    },
    cancel() {},
  });

  const older = transition.select("dashboard", "preserve", {
    query: "?region=older",
    hash: "#first",
  });
  const newer = transition.select("dashboard", "preserve", {
    query: "?region=newer",
    hash: "#second",
  });
  first.resolve(true);
  assert.equal(await older, false);
  second.resolve(true);
  assert.equal(await newer, true);
  assert.deepEqual(committed, [
    ["dashboard", "preserve", false, { query: "?region=newer", hash: "#second" }],
  ]);
});

test("an aborted transition settles before late preparation can commit", async () => {
  const prepared = deferred<boolean>();
  const commit = vi.fn(() => true);
  const cancel = vi.fn();
  const transition = new ViewTransition("dashboard", {
    prepare: () => prepared.promise,
    commit,
    cancel,
  });

  const owner = new AbortController();
  const selecting = transition.select("report", "develop", undefined, owner.signal);
  owner.abort();

  assert.equal(await selecting, false);
  prepared.resolve(true);
  await Promise.resolve();
  assert.equal(commit.mock.calls.length, 0);
  assert.equal(cancel.mock.calls.length, 1);
});

test("a failed staged view can be retried from the previous selection", async () => {
  const changed: boolean[] = [];
  const rollback = vi.fn();
  let ready = false;
  const transition = new ViewTransition("dashboard", {
    prepare: async () => true,
    stage(_view, viewChanged) {
      changed.push(viewChanged);
      return { ready: Promise.resolve(ready), rollback };
    },
    commit: () => true,
    cancel: vi.fn(),
  });

  assert.equal(await transition.select("report", "develop"), false);
  ready = true;
  assert.equal(await transition.select("report", "develop"), true);

  assert.deepEqual(changed, [true, true]);
  assert.equal(rollback.mock.calls.length, 1);
});

test("a failed replacement restores the committed view after superseding a staged view", async () => {
  const reportReady = deferred<boolean>();
  const reportRollback = deferred<void>();
  const rollbacks: string[] = [];
  const unhandled = vi.fn();
  let presented = "dashboard";
  let presentedWhenStorySettled: string | undefined;
  process.on("unhandledRejection", unhandled);
  try {
    const transition = new ViewTransition("dashboard", {
      prepare: async () => true,
      stage(view) {
        const previous = presented;
        presented = view;
        return {
          ready: view === "report" ? reportReady.promise : Promise.resolve(false),
          rollback: async () => {
            rollbacks.push(view);
            if (view === "report") {
              await reportRollback.promise;
            }
            presented = previous;
          },
        };
      },
      commit: vi.fn(() => true),
      cancel: vi.fn(),
    });

    const report = transition.select("report", "preserve");
    await vi.waitFor(() => assert.equal(presented, "report"));
    const story = transition.select("story", "preserve");
    void story.then(() => {
      presentedWhenStorySettled = presented;
    });
    reportReady.resolve(true);
    await new Promise((resolve) => setTimeout(resolve, 0));

    assert.equal(presentedWhenStorySettled, undefined);
    reportRollback.resolve();
    assert.deepEqual(await Promise.all([report, story]), [false, false]);
    await new Promise((resolve) => setTimeout(resolve, 0));

    assert.equal(presented, "dashboard");
    assert.equal(presentedWhenStorySettled, "dashboard");
    assert.deepEqual(rollbacks, ["report", "story"]);
    assert.equal(unhandled.mock.calls.length, 0);
  } finally {
    process.off("unhandledRejection", unhandled);
  }
});

test("cancel observes one staged rollback rejection", async () => {
  const ready = deferred<boolean>();
  const staged = deferred<void>();
  const rollback = vi.fn(async () => {
    throw new Error("rollback failed");
  });
  const unhandled = vi.fn();
  process.on("unhandledRejection", unhandled);
  try {
    const transition = new ViewTransition("dashboard", {
      prepare: async () => true,
      stage: () => {
        staged.resolve();
        return { ready: ready.promise, rollback };
      },
      commit: vi.fn(() => true),
      cancel: vi.fn(),
    });

    const selecting = transition.select("report", "preserve");
    await staged.promise;
    transition.cancel();
    ready.resolve(true);

    assert.equal(await selecting, false);
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(rollback.mock.calls.length, 1);
    assert.equal(unhandled.mock.calls.length, 0);
  } finally {
    process.off("unhandledRejection", unhandled);
  }
});

test("stale preflight work cannot start a source transition", async () => {
  const preflights = new Map<string, ReturnType<typeof deferred<string>>>();
  const prepared: string[] = [];
  const committed: string[] = [];
  const transition = new ViewTransition<string>("dashboard", {
    preflight(view) {
      const preflight = deferred<string>();
      preflights.set(view, preflight);
      return preflight.promise;
    },
    async prepare(view) {
      prepared.push(view);
      return true;
    },
    commit(view) {
      committed.push(view);
    },
    cancel() {},
  });

  const first = transition.select("operations", "split");
  const second = transition.select("executive", "preserve");
  preflights.get("executive")!.resolve("server");
  assert.equal(await second, true);
  preflights.get("operations")!.resolve("server");
  assert.equal(await first, false);

  assert.deepEqual(prepared, ["executive"]);
  assert.deepEqual(committed, ["executive"]);
});

test("a newer failed preflight cancels source work already in progress", async () => {
  const sourceGate = deferred<void>();
  const sourceStarted = deferred<void>();
  const preflightFailure = new Error("runtime availability failed");
  let sourceGeneration = 0;
  const committed: string[] = [];
  const transition = new ViewTransition<string>("dashboard", {
    async preflight(view) {
      if (view === "executive") {
        throw preflightFailure;
      }
      return "server";
    },
    async prepare() {
      const generation = sourceGeneration;
      sourceStarted.resolve();
      await sourceGate.promise;
      return generation === sourceGeneration;
    },
    commit(view) {
      committed.push(view);
    },
    cancel() {
      sourceGeneration += 1;
    },
  });

  const first = transition.select("operations", "split");
  await sourceStarted.promise;
  await assert.rejects(transition.select("executive", "preserve"), preflightFailure);
  sourceGate.resolve();

  assert.equal(await first, false);
  assert.deepEqual(committed, []);
});

test("disposing a transition aborts its active preflight once", async () => {
  let cancellations = 0;
  const committed: string[] = [];
  const transition = new ViewTransition<string>("dashboard", {
    preflight: async (_view, signal) =>
      await new Promise<string>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      }),
    async prepare() {
      return true;
    },
    commit(view) {
      committed.push(view);
    },
    cancel() {
      cancellations += 1;
    },
  });

  const selecting = transition.select("operations", "split");
  transition.dispose();
  transition.dispose();

  assert.equal(await selecting, false);
  assert.equal(await transition.select("executive", "preserve"), false);
  assert.equal(cancellations, 2);
  assert.deepEqual(committed, []);
});
