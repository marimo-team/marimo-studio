import { assertEquals } from "@std/assert";

import { ViewTransition } from "../src/studio/view-transition.ts";

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

Deno.test("the latest view request is the only transition committed", async () => {
  const loads = new Map<string, ReturnType<typeof deferred<boolean>>>();
  const committed: string[] = [];
  const transition = new ViewTransition("dashboard", {
    prepare(view) {
      const load = deferred<boolean>();
      loads.set(view, load);
      return load.promise;
    },
    commit(view) {
      committed.push(view);
    },
    cancel() {},
  });

  const first = transition.select("operations");
  const second = transition.select("executive");
  loads.get("executive")!.resolve(true);
  assertEquals(await second, true);
  loads.get("operations")!.resolve(true);
  assertEquals(await first, false);

  assertEquals(committed, ["executive"]);
});

Deno.test("choosing the current view cancels a pending transition", async () => {
  const pending = deferred<boolean>();
  const committed: string[] = [];
  let cancellations = 0;
  const transition = new ViewTransition("dashboard", {
    prepare() {
      return pending.promise;
    },
    commit(view) {
      committed.push(view);
    },
    cancel() {
      cancellations += 1;
    },
  });

  const switching = transition.select("operations");
  assertEquals(await transition.select("dashboard"), true);
  pending.resolve(true);

  assertEquals(await switching, false);
  assertEquals(cancellations, 1);
  assertEquals(committed, []);
});
