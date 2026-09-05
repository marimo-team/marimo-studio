import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { ProjectionReadGate } from "../src/projections/read-gate.ts";

test("a presentation refresh cancels old reads and releases current reads together", async () => {
  const gate = new ProjectionReadGate();
  const oldRead = gate.run(
    undefined,
    (signal) =>
      new Promise<void>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      }),
  );
  const claim = gate.begin();
  await assert.rejects(oldRead, { name: "AbortError" });
  let started = false;
  const currentRead = gate.run(undefined, async () => {
    started = true;
  });
  await Promise.resolve();
  assert.equal(started, false);

  gate.complete(claim);
  await currentRead;
  assert.equal(started, true);
});

test("a notebook mutation pauses new reads and drains active reads without aborting", async () => {
  const gate = new ProjectionReadGate();
  let finish!: () => void;
  let aborted = false;
  const active = gate.run(
    undefined,
    (signal) =>
      new Promise<void>((resolve) => {
        finish = resolve;
        signal.addEventListener("abort", () => {
          aborted = true;
        });
      }),
  );
  const pausing = gate.pauseAndDrainCurrent();
  let nextStarted = false;
  const next = gate.run(undefined, async () => {
    nextStarted = true;
  });
  await Promise.resolve();
  assert.equal(nextStarted, false);
  assert.equal(aborted, false);

  finish();
  await active;
  const claim = await pausing;
  assert.equal(aborted, false);
  assert.equal(nextStarted, false);

  gate.complete(claim);
  await next;
  assert.equal(nextStarted, true);
});

test("a cancelled mutation barrier reopens reads without aborting the active read", async () => {
  const gate = new ProjectionReadGate();
  let finish!: () => void;
  let activeAborted = false;
  const active = gate.run(
    undefined,
    (signal) =>
      new Promise<void>((resolve) => {
        finish = resolve;
        signal.addEventListener("abort", () => {
          activeAborted = true;
        });
      }),
  );
  const controller = new AbortController();
  const pausing = gate.pauseAndDrainCurrent(controller.signal);
  let nextStarted = false;
  const next = gate.run(undefined, async () => {
    nextStarted = true;
  });
  await Promise.resolve();
  assert.equal(nextStarted, false);

  controller.abort(new DOMException("The parent abandoned the mutation.", "AbortError"));
  await assert.rejects(pausing, { name: "AbortError" });
  await next;
  assert.equal(nextStarted, true);
  assert.equal(activeAborted, false);
  finish();
  await active;
});

test("concurrent mutation pauses share one claim", async () => {
  const gate = new ProjectionReadGate();
  const first = gate.pauseAndDrain();
  const second = gate.pauseAndDrain();

  const [firstClaim, secondClaim] = await Promise.all([first, second]);
  assert.deepEqual(secondClaim, firstClaim);
  assert.equal(gate.current(firstClaim), true);
  gate.complete(firstClaim);
});

test("a superseding refresh keeps ownership while a mutation drain finishes", async () => {
  const gate = new ProjectionReadGate();
  const active = gate.run(
    undefined,
    (signal) =>
      new Promise<void>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      }),
  );
  const pausing = gate.pauseAndDrainCurrent();
  const refresh = gate.begin();

  await assert.rejects(active, { name: "AbortError" });
  gate.complete(refresh);
  const mutation = await pausing;
  assert.equal(gate.current(refresh), false);
  assert.equal(gate.current(mutation), true);
  assert.ok(mutation.generation > refresh.generation);
  gate.complete(mutation);
});

test("a pending refresh hands ownership to a mutation without reopening reads", async () => {
  const gate = new ProjectionReadGate();
  let finish!: () => void;
  const active = gate.run(
    undefined,
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const refresh = gate.begin();
  const pausing = gate.pauseAndDrainCurrent();
  let started = false;
  let paused = false;
  void pausing.then(() => {
    paused = true;
  });

  gate.complete(refresh);
  const read = gate.run(undefined, async () => {
    started = true;
  });
  await Promise.resolve();
  assert.equal(started, false);
  assert.equal(paused, false);

  finish();
  await active;

  const mutation = await pausing;
  assert.equal(gate.current(mutation), true);
  assert.equal(started, false);
  gate.complete(mutation);
  await read;
  assert.equal(started, true);
});
