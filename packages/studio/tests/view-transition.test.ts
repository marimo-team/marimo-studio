import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { ViewTransition } from "../src/views/transition.ts";

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
    },
    cancel() {},
  });

  const first = transition.select("operations", "split");
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
    prepare() {
      return pending.promise;
    },
    commit(view, landing, changed) {
      committed.push([view, landing, changed]);
    },
    cancel() {
      cancellations += 1;
    },
  });

  const switching = transition.select("operations", "preserve");
  assert.deepEqual(await transition.select("dashboard", "split"), true);
  pending.resolve(true);

  assert.deepEqual(await switching, false);
  assert.deepEqual(cancellations, 1);
  assert.deepEqual(committed, [["dashboard", "split", false]]);
});
