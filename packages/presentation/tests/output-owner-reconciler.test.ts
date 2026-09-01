import assert from "node:assert/strict";
import { test, vi } from "vite-plus/test";

import type { OutputReader } from "../src/outputs/reader";

import { OutputRequestError } from "../src/outputs/remote";
import { OutputOwnerReconciler } from "../src/runtime/outputs/output-owner-reconciler";
import { projectionRequest } from "./runtime-fixtures";

const request = (active: ReturnType<typeof projectionRequest>[], revision = "revision-a") => ({
  revision,
  projections: [],
  activeProjections: active,
});

const renderRequest = (active: ReturnType<typeof projectionRequest>, revision = "revision-a") => ({
  revision,
  projections: [active],
  activeProjections: [active],
});

const emptyResponse = { outputs: {}, errors: {} };
const projectionRevisionA = "a".repeat(64);
const projectionRevisionB = "b".repeat(64);

const deferredResponse = () => {
  let resolve = () => {};
  let reject = (_error: Error) => {};
  const promise = new Promise<typeof emptyResponse>((accept, decline) => {
    resolve = () => accept(emptyResponse);
    reject = decline;
  });
  return { promise, reject, resolve };
};

test("waits for an output read before reconciling ownership", async () => {
  const active = projectionRequest("report", "output");
  const requests: { active: string[]; requested: string[] }[] = [];
  const reader: OutputReader = (value) => {
    requests.push({
      active: value.activeProjections.map((projection) => projection.target),
      requested: value.projections.map((projection) => projection.target),
    });
    return Promise.resolve({ outputs: {}, errors: {} });
  };
  const reconciler = new OutputOwnerReconciler(reader, 0);

  reconciler.update(projectionRevisionA, request([]));
  reconciler.update(projectionRevisionA, request([active]));
  assert.deepEqual(requests, []);

  await reconciler.read(projectionRevisionA, renderRequest(active));
  reconciler.update(projectionRevisionA, request([]));
  await Promise.resolve();
  reconciler.dispose();

  assert.deepEqual(requests, [
    { active: ["report"], requested: ["report"] },
    { active: [], requested: [] },
  ]);
});

test("advances the wire revision without restarting an unchanged projection", async () => {
  const active = projectionRequest("report", "output");
  const rendered = deferredResponse();
  const requests: string[] = [];
  let aborted = 0;
  const reader: OutputReader = (value, signal) => {
    requests.push(value.revision);
    signal?.addEventListener("abort", () => aborted++, { once: true });
    return value.projections.length > 0 ? rendered.promise : Promise.resolve(emptyResponse);
  };
  const reconciler = new OutputOwnerReconciler(reader, 0);

  reconciler.update(projectionRevisionA, request([active], "revision-a"));
  const pending = reconciler.read(projectionRevisionA, renderRequest(active));
  await Promise.resolve();
  reconciler.update(projectionRevisionA, request([active], "revision-b"));

  assert.deepEqual(requests, ["revision-a"]);
  assert.equal(aborted, 0);
  rendered.resolve();
  await pending;
  reconciler.update(projectionRevisionA, request([], "revision-b"));
  await Promise.resolve();
  await Promise.resolve();

  assert.deepEqual(requests, ["revision-a", "revision-b"]);
  assert.equal(aborted, 0);
  reconciler.dispose();
});

test("reconciles an ownership-creating read that aborts after dispatch", async () => {
  const active = projectionRequest("report", "output");
  const dispatched = deferredResponse();
  let readStarted = () => {};
  const readReady = new Promise<void>((resolve) => {
    readStarted = resolve;
  });
  let cleanupCalls = 0;
  let cleaned = () => {};
  const cleanupReady = new Promise<void>((resolve) => {
    cleaned = resolve;
  });
  const reader: OutputReader = (value) => {
    if (value.projections.length === 0) {
      cleanupCalls += 1;
      cleaned();
      return Promise.resolve({ outputs: {}, errors: {} });
    }
    readStarted();
    return dispatched.promise;
  };
  const reconciler = new OutputOwnerReconciler(reader, 0);
  const controller = new AbortController();

  reconciler.update(projectionRevisionA, request([active]));
  const pending = reconciler.read(projectionRevisionA, renderRequest(active), controller.signal);
  await readReady;
  reconciler.update(projectionRevisionA, request([]));
  controller.abort();

  await assert.rejects(pending, { name: "AbortError" });
  dispatched.resolve();
  await cleanupReady;
  assert.equal(cleanupCalls, 1);
  reconciler.dispose();
});

test("dispatches only the latest queued source version", async () => {
  const blocker = projectionRequest("blocker", "output");
  const active = projectionRequest("report", "output");
  const canceledTarget = projectionRequest("canceled", "output");
  const blocked = deferredResponse();
  const requestedTargets: string[][] = [];
  let blockerStarted = () => {};
  const blockerReady = new Promise<void>((resolve) => {
    blockerStarted = resolve;
  });
  let convergenceStarted = false;
  let converged = () => {};
  const convergenceReady = new Promise<void>((resolve) => {
    converged = resolve;
  });
  const reader: OutputReader = (value) => {
    const targets = value.projections.map((projection) => projection.target);
    requestedTargets.push(targets);
    const target = targets[0];
    if (target === blocker.target) {
      blockerStarted();
      return blocked.promise;
    }
    if (convergenceStarted) {
      converged();
    }
    return Promise.resolve(emptyResponse);
  };
  const reconciler = new OutputOwnerReconciler(reader, 0);
  const blockingRead = reconciler.read(projectionRevisionA, renderRequest(blocker));
  await blockerReady;

  const canceledController = new AbortController();
  const canceled = reconciler.read(
    projectionRevisionA,
    renderRequest(canceledTarget),
    canceledController.signal,
  );
  canceledController.abort();

  const staleController = new AbortController();
  const stale = reconciler.read(projectionRevisionA, renderRequest(active), staleController.signal);
  staleController.abort();
  const latest = reconciler.read(projectionRevisionA, renderRequest(active));

  blocked.resolve();
  await blockingRead;
  await assert.rejects(canceled, { name: "AbortError" });
  await assert.rejects(stale, { name: "AbortError" });
  await latest;

  assert.deepEqual(requestedTargets, [["blocker"], ["report"]]);

  convergenceStarted = true;
  reconciler.update(projectionRevisionA, request([active, canceledTarget]));
  await convergenceReady;
  assert.deepEqual(requestedTargets.at(-1), ["report"]);
  reconciler.dispose();
});

test("dispose aborts a started read and skips its queued successor", async () => {
  const first = projectionRequest("first", "output");
  const second = projectionRequest("second", "output");
  const targets: string[] = [];
  let firstStarted = () => {};
  const firstReady = new Promise<void>((resolve) => {
    firstStarted = resolve;
  });
  const reader: OutputReader = (value, signal) => {
    const target = value.projections[0]?.target;
    if (target) {
      targets.push(target);
    }
    if (target !== first.target) {
      return Promise.resolve(emptyResponse);
    }
    firstStarted();
    return new Promise((_resolve, reject) => {
      signal?.addEventListener("abort", () => reject(signal.reason), { once: true });
    });
  };
  const reconciler = new OutputOwnerReconciler(reader, 0);
  const started = reconciler.read(projectionRevisionA, renderRequest(first));
  await firstReady;
  const queued = reconciler.read(projectionRevisionA, renderRequest(second));

  reconciler.dispose();

  await assert.rejects(started, { name: "AbortError" });
  await assert.rejects(queued, { name: "AbortError" });
  assert.deepEqual(targets, ["first"]);
});

test("restores an active target after an in-flight cleanup", async () => {
  const active = projectionRequest("report", "output");
  const cleanup = deferredResponse();
  let cleanupStarted = () => {};
  const cleanupReady = new Promise<void>((resolve) => {
    cleanupStarted = resolve;
  });
  let renderCalls = 0;
  let restored = () => {};
  const restoreReady = new Promise<void>((resolve) => {
    restored = resolve;
  });
  const requests: { active: string[]; requested: string[] }[] = [];
  const reader: OutputReader = (value) => {
    const recorded = {
      active: value.activeProjections.map((projection) => projection.target),
      requested: value.projections.map((projection) => projection.target),
    };
    requests.push(recorded);
    if (recorded.active.length === 0) {
      cleanupStarted();
      return cleanup.promise;
    }
    renderCalls += 1;
    if (renderCalls > 1) {
      restored();
    }
    return Promise.resolve(emptyResponse);
  };
  const reconciler = new OutputOwnerReconciler(reader, 0);

  reconciler.update(projectionRevisionA, request([active]));
  await reconciler.read(projectionRevisionA, renderRequest(active));
  reconciler.update(projectionRevisionA, request([]));
  await cleanupReady;
  reconciler.update(projectionRevisionA, request([active]));
  cleanup.resolve();
  await restoreReady;

  assert.deepEqual(requests.at(-1), {
    active: ["report"],
    requested: ["report"],
  });
  reconciler.dispose();
});

test("keeps a replacement target after an older plan settles", async () => {
  const first = projectionRequest("first", "output");
  const second = projectionRequest("second", "output");
  const secondRead = deferredResponse();
  const staleFirst = deferredResponse();
  let staleStarted = () => {};
  const staleReady = new Promise<void>((resolve) => {
    staleStarted = resolve;
  });
  let secondCalls = 0;
  let restored = () => {};
  const restoreReady = new Promise<void>((resolve) => {
    restored = resolve;
  });
  let firstCalls = 0;
  const requests: { active: string[]; requested: string[] }[] = [];
  const reader: OutputReader = (value) => {
    const recorded = {
      active: value.activeProjections.map((projection) => projection.target),
      requested: value.projections.map((projection) => projection.target),
    };
    requests.push(recorded);
    if (recorded.requested.includes("second")) {
      secondCalls += 1;
      if (secondCalls > 1) {
        restored();
      }
      return secondRead.promise;
    }
    if (recorded.requested.includes("first")) {
      firstCalls += 1;
      if (firstCalls > 1) {
        staleStarted();
        return staleFirst.promise;
      }
    }
    return Promise.resolve(emptyResponse);
  };
  const reconciler = new OutputOwnerReconciler(reader, 0);

  reconciler.update(projectionRevisionA, request([first]));
  await reconciler.read(projectionRevisionA, renderRequest(first));
  const replacement = reconciler.read(projectionRevisionA, renderRequest(second));
  secondRead.resolve();
  await replacement;
  await staleReady;
  reconciler.update(projectionRevisionA, request([second]));
  staleFirst.resolve();
  await restoreReady;

  assert.deepEqual(requests.at(-1), {
    active: ["second"],
    requested: ["second"],
  });
  reconciler.dispose();
});

test("retries current ownership after a canceled read advances the wire revision", async () => {
  vi.useFakeTimers();
  const active = projectionRequest("report", "output");
  const cleanupRevisions: string[] = [];
  const reader: OutputReader = (value) => {
    if (value.projections.length > 0) {
      return Promise.resolve(emptyResponse);
    }
    cleanupRevisions.push(value.revision);
    if (cleanupRevisions.length === 1) {
      return Promise.reject(
        new OutputRequestError("connection reset", "output-network-failed", true),
      );
    }
    return Promise.resolve(emptyResponse);
  };
  const reconciler = new OutputOwnerReconciler(reader, 1_000);

  try {
    reconciler.update(projectionRevisionA, request([active], "revision-a"));
    await reconciler.read(projectionRevisionA, renderRequest(active, "revision-a"));
    reconciler.update(projectionRevisionA, request([], "revision-a"));
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    assert.equal(vi.getTimerCount(), 1);

    const controller = new AbortController();
    const canceled = reconciler.read(
      projectionRevisionA,
      renderRequest(active, "revision-b"),
      controller.signal,
    );
    controller.abort();
    await assert.rejects(canceled, { name: "AbortError" });
    await vi.advanceTimersByTimeAsync(1_000);

    assert.deepEqual(cleanupRevisions, ["revision-a", "revision-b"]);
  } finally {
    reconciler.dispose();
    vi.useRealTimers();
  }
});

test("a projection revision clears its final native owner with transient retry", async () => {
  const active = projectionRequest("report", "output");
  const cleanups: string[] = [];
  let cleaned = () => {};
  const cleanupReady = new Promise<void>((resolve) => {
    cleaned = resolve;
  });
  const reader: OutputReader = (value) => {
    if (value.projections.length > 0) {
      return Promise.resolve(emptyResponse);
    }
    cleanups.push(value.revision);
    if (cleanups.length === 1) {
      return Promise.reject(
        new OutputRequestError("connection reset", "output-network-failed", true),
      );
    }
    cleaned();
    return Promise.resolve(emptyResponse);
  };
  const reconciler = new OutputOwnerReconciler(reader, 0);

  reconciler.update(projectionRevisionA, request([active], "revision-a"));
  await reconciler.read(projectionRevisionA, renderRequest(active, "revision-a"));
  reconciler.update(projectionRevisionB, request([], "revision-b"));
  await cleanupReady;
  reconciler.dispose();

  assert.deepEqual(cleanups, ["revision-b", "revision-b"]);
});

test("ignores an old transient failure after reconnect", async () => {
  const first = projectionRequest("first", "output");
  const second = projectionRequest("second", "output");
  const staleCleanup = deferredResponse();
  let cleanupCalls = 0;
  let staleStarted = () => {};
  const staleReady = new Promise<void>((resolve) => {
    staleStarted = resolve;
  });
  let finalCleanup = () => {};
  const finalCleanupReady = new Promise<void>((resolve) => {
    finalCleanup = resolve;
  });
  const reader: OutputReader = (value) => {
    if (value.projections.length > 0) {
      return Promise.resolve(emptyResponse);
    }
    cleanupCalls += 1;
    if (cleanupCalls === 1) {
      staleStarted();
      return staleCleanup.promise;
    }
    finalCleanup();
    return Promise.resolve(emptyResponse);
  };
  const reconciler = new OutputOwnerReconciler(reader, 0);

  reconciler.update(projectionRevisionA, request([first]));
  await reconciler.read(projectionRevisionA, renderRequest(first));
  reconciler.update(projectionRevisionA, request([]));
  await staleReady;
  reconciler.pause();
  reconciler.update(projectionRevisionA, request([second]));
  const reconnected = reconciler.read(projectionRevisionA, renderRequest(second));
  reconciler.update(projectionRevisionA, request([]));
  staleCleanup.reject(new OutputRequestError("connection reset", "output-network-failed", true));

  await reconnected;
  await finalCleanupReady;
  assert.equal(cleanupCalls, 2);
  reconciler.dispose();
});

test("continues with a newer revision after an old permanent failure", async () => {
  const active = projectionRequest("report", "output");
  const staleCleanup = deferredResponse();
  const cleanupRevisions: string[] = [];
  let staleStarted = () => {};
  const staleReady = new Promise<void>((resolve) => {
    staleStarted = resolve;
  });
  let currentCleanup = () => {};
  const currentCleanupReady = new Promise<void>((resolve) => {
    currentCleanup = resolve;
  });
  const reader: OutputReader = (value) => {
    if (value.projections.length > 0) {
      return Promise.resolve(emptyResponse);
    }
    cleanupRevisions.push(value.revision);
    if (value.revision === "revision-a") {
      staleStarted();
      return staleCleanup.promise;
    }
    currentCleanup();
    return Promise.resolve(emptyResponse);
  };
  const reconciler = new OutputOwnerReconciler(reader, 0);

  reconciler.update(projectionRevisionA, request([active], "revision-a"));
  await reconciler.read(projectionRevisionA, renderRequest(active));
  reconciler.update(projectionRevisionA, request([], "revision-a"));
  await staleReady;
  reconciler.update(projectionRevisionA, request([], "revision-b"));
  staleCleanup.reject(new OutputRequestError("invalid revision", "output-request-failed", false));

  await currentCleanupReady;
  assert.deepEqual(cleanupRevisions, ["revision-a", "revision-b"]);
  reconciler.dispose();
});

test("a projection revision aborts one dirty read and waits for its next owner", async () => {
  const active = projectionRequest("report", "output");
  const requests: { active: string[]; requested: string[]; revision: string }[] = [];
  let oldReadStarted = () => {};
  const oldReadReady = new Promise<void>((resolve) => {
    oldReadStarted = resolve;
  });
  let aborts = 0;
  const reader: OutputReader = (value, signal) => {
    requests.push({
      active: value.activeProjections.map((projection) => projection.target),
      requested: value.projections.map((projection) => projection.target),
      revision: value.revision,
    });
    if (value.revision === "revision-a" && value.projections.length > 0) {
      oldReadStarted();
      return new Promise((_resolve, reject) => {
        signal?.addEventListener(
          "abort",
          () => {
            aborts += 1;
            reject(new DOMException("The projection revision changed.", "AbortError"));
          },
          { once: true },
        );
      });
    }
    return Promise.resolve(emptyResponse);
  };
  const reconciler = new OutputOwnerReconciler(reader, 0);

  reconciler.update(projectionRevisionA, request([active], "revision-a"));
  const oldRead = reconciler.read(projectionRevisionA, renderRequest(active));
  await oldReadReady;
  reconciler.update(projectionRevisionB, request([], "revision-b"));

  await assert.rejects(oldRead, { name: "AbortError" });
  assert.equal(aborts, 1);
  assert.equal(requests.length, 1);

  await reconciler.read(projectionRevisionB, renderRequest(active, "revision-b"));
  assert.deepEqual(requests.at(-1), {
    active: ["report"],
    requested: ["report"],
    revision: "revision-b",
  });
  reconciler.dispose();
});

test("waits for a new read after reconnect", async () => {
  const active = projectionRequest("report", "output");
  let cleanupCalls = 0;
  const reader: OutputReader = (value) => {
    if (value.projections.length === 0) {
      cleanupCalls += 1;
    }
    return Promise.resolve({ outputs: {}, errors: {} });
  };
  const reconciler = new OutputOwnerReconciler(reader, 0);

  await reconciler.read(projectionRevisionA, renderRequest(active));
  reconciler.pause();
  reconciler.update(projectionRevisionA, request([]));
  await Promise.resolve();
  reconciler.dispose();

  assert.equal(cleanupCalls, 0);
});
