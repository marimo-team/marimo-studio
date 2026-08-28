import assert from "node:assert/strict";
import { test, vi } from "vite-plus/test";

import type { ValueReader } from "../src/values/reader.ts";

import { ProjectionOwnerReconciler } from "../src/runtime/projection-owner-reconciler.ts";
import { ValueRequestError } from "../src/values/remote.ts";
import { projectionRequest } from "./runtime-fixtures.ts";

const projectionRevision = "a".repeat(64);

test("value ownership converges after the final host is removed", async () => {
  const active = projectionRequest("frame", "value");
  const requests: Array<{ active: string[]; requested: string[] }> = [];
  const reader: ValueReader = async (request) => {
    requests.push({
      active: request.activeProjections.map((projection) => projection.target),
      requested: request.projections.map((projection) => projection.target),
    });
    return { values: {}, errors: {} };
  };
  const reconciler = new ProjectionOwnerReconciler(
    reader,
    0,
    (error) => error instanceof ValueRequestError && error.transient,
    () => [],
    true,
  );
  const activeRequest = {
    revision: "revision-a",
    projections: [active],
    activeProjections: [active],
  };

  reconciler.update(projectionRevision, {
    ...activeRequest,
    projections: [],
  });
  await reconciler.read(projectionRevision, activeRequest);
  reconciler.update(projectionRevision, {
    revision: "revision-a",
    projections: [],
    activeProjections: [],
  });

  await vi.waitFor(() => assert.equal(requests.length, 2));
  assert.deepEqual(requests, [
    { active: ["frame"], requested: ["frame"] },
    { active: [], requested: [] },
  ]);
  reconciler.dispose();
});

test("value caller cancellation stops dispatched browser work", async () => {
  const active = projectionRequest("frame", "value");
  let sourceSignal: AbortSignal | undefined;
  let started = () => {};
  const ready = new Promise<void>((resolve) => {
    started = resolve;
  });
  const reader: ValueReader = (request, signal) => {
    if (request.projections.length === 0) {
      return Promise.resolve({ values: {}, errors: {} });
    }
    sourceSignal = signal;
    started();
    return new Promise((_resolve, reject) => {
      signal?.addEventListener("abort", () => reject(signal.reason), { once: true });
    });
  };
  const reconciler = new ProjectionOwnerReconciler(
    reader,
    0,
    (error) => error instanceof ValueRequestError && error.transient,
    () => [],
    true,
  );
  const request = {
    revision: "revision-a",
    projections: [active],
    activeProjections: [active],
  };
  const controller = new AbortController();
  reconciler.update(projectionRevision, { ...request, projections: [] });
  const pending = reconciler.read(projectionRevision, request, controller.signal);
  await ready;

  controller.abort();

  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(sourceSignal?.aborted, true);
  reconciler.dispose();
});
