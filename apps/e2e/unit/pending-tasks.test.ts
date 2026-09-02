import { expect, test } from "vite-plus/test";

import { drainPendingTasks } from "../tests/pending-tasks.ts";

test("drains tasks queued by a completing decoder", async () => {
  const pending = new Set<Promise<void>>();
  const completed: string[] = [];
  const track = (task: Promise<void>) => {
    pending.add(task);
    void task.then(() => pending.delete(task));
  };
  let release: () => void = () => {};
  const first = new Promise<void>((resolve) => {
    release = resolve;
  }).then(() => {
    completed.push("first");
    track(
      Promise.resolve().then(() => {
        completed.push("second");
      }),
    );
  });
  track(first);

  const drained = drainPendingTasks(pending);
  release();
  await drained;

  expect(completed).toEqual(["first", "second"]);
  expect(pending.size).toBe(0);
});

test("observes a decoder queued during the empty-set microtask turn", async () => {
  const pending = new Set<Promise<void>>();
  let completed = false;
  queueMicrotask(() => {
    const task = Promise.resolve().then(() => {
      completed = true;
    });
    pending.add(task);
    void task.then(() => pending.delete(task));
  });

  await drainPendingTasks(pending);

  expect(completed).toBe(true);
  expect(pending.size).toBe(0);
});
