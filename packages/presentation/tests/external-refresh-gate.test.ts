import {
  ProjectedOutputFunctionGate,
  type ProjectedOutputFunctionTransition,
} from "@marimo-studio/marimo-frontend/projected-output-function-gate";
import assert from "node:assert/strict";
import { test, vi } from "vite-plus/test";

import type { ProjectionRefreshClaim } from "../src/projections/read-gate.ts";

import { ExternalRefreshGate } from "../src/document/external-refresh-gate.ts";
import { ProjectionReadGate } from "../src/projections/read-gate.ts";

const projectionGate = () => {
  let generation = 0;
  return {
    begin: vi.fn(() => ({ generation: ++generation })),
    complete: vi.fn((_claim: ProjectionRefreshClaim) => {}),
    pauseAndDrainCurrent: vi.fn(async () => ({ generation: ++generation })),
  };
};

const functionGate = (drained: Promise<void> = Promise.resolve()) => {
  let generation = 0;
  const owner = new ProjectedOutputFunctionGate();
  return {
    begin: vi.fn((): ProjectedOutputFunctionTransition => ({
      cancelDrain: vi.fn(),
      drained,
      gate: owner,
      generation: ++generation,
    })),
    cancel: vi.fn(),
    complete: vi.fn(),
  };
};

test("a failed later barrier cannot release an earlier accepted refresh", async () => {
  const projections = projectionGate();
  const functions = functionGate();
  const gate = new ExternalRefreshGate(projections, functions);
  const first = gate.acquire("mutation");
  const second = gate.acquire("mutation");
  await Promise.all([first.drained, second.drained]);

  second.release();
  assert.equal(projections.complete.mock.calls.length, 0);
  assert.equal(functions.complete.mock.calls.length, 0);

  gate.presentationChanged();
  assert.equal(projections.complete.mock.calls.length, 1);
  assert.equal(functions.complete.mock.calls.length, 1);
});

test("successive standalone builds acquire fresh refresh claims", () => {
  const projections = projectionGate();
  const functions = functionGate();
  const gate = new ExternalRefreshGate(projections, functions);

  gate.acquire("refresh").release();
  gate.acquire("refresh").release();

  assert.equal(projections.begin.mock.calls.length, 2);
  assert.equal(functions.begin.mock.calls.length, 2);
  assert.deepEqual(
    projections.complete.mock.calls.map(([claim]) => claim.generation),
    [1, 2],
  );
});

test("a mutation during a refresh waits for the active projection read", async () => {
  const projections = new ProjectionReadGate();
  const functions = functionGate();
  const gate = new ExternalRefreshGate(projections, functions);
  let finish!: () => void;
  const activeRead = projections.run(
    undefined,
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const refresh = gate.acquire("refresh");
  const mutation = gate.acquire("mutation");
  let drained = false;
  void mutation.drained.then(() => {
    drained = true;
  });

  await Promise.resolve();
  assert.equal(drained, false);

  finish();
  await activeRead;
  await mutation.drained;
  assert.equal(drained, true);
  refresh.release();
  gate.presentationChanged();
});

test("build settlement cannot release an undrained mutation owner", async () => {
  const projections = projectionGate();
  let finishFunctionDrain = () => {};
  const functionDrain = new Promise<void>((resolve) => {
    finishFunctionDrain = resolve;
  });
  const functions = functionGate(functionDrain);
  const gate = new ExternalRefreshGate(projections, functions);
  const refresh = gate.acquire("refresh");
  const mutation = gate.acquire("mutation");
  let drained = false;
  void mutation.drained.then(() => {
    drained = true;
  });

  refresh.release();
  await Promise.resolve();
  assert.equal(drained, false);
  assert.equal(projections.complete.mock.calls.length, 0);
  assert.equal(functions.complete.mock.calls.length, 0);

  finishFunctionDrain();
  await mutation.drained;
  gate.presentationChanged();
});

test("a presentation change rejects an undrained mutation owner", async () => {
  const projections = projectionGate();
  const functions = functionGate(new Promise<void>(() => {}));
  const gate = new ExternalRefreshGate(projections, functions);
  const mutation = gate.acquire("mutation");
  const rejected = assert.rejects(mutation.drained, { name: "AbortError" });

  gate.presentationChanged();

  await rejected;
});
