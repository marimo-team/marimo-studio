import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  BaselineReconciler,
  RefreshRetrySchedule,
  samePresentationRevision,
  PresentationRefreshState,
  StaleBindingRefresh,
} from "../src/document/presentation-refresh.ts";

const dashboard = {
  documentUrl: "/studio/dashboard/",
  supportUrl: "/_marimo-studio/views/dashboard",
};
const executive = {
  documentUrl: "/studio/executive/",
  supportUrl: "/_marimo-studio/views/executive",
};

test("a revision identifies one published presentation across capability URLs", () => {
  const current = { ...dashboard, revision: "same" };

  assert.deepEqual(samePresentationRevision(current, { ...current }), true);
  assert.deepEqual(samePresentationRevision(current, { ...current, revision: "changed" }), false);
  assert.deepEqual(samePresentationRevision(current, { ...current, documentUrl: "/other/" }), true);
  assert.deepEqual(
    samePresentationRevision(current, {
      ...current,
      supportUrl: "/_marimo-studio/views/other",
    }),
    true,
  );
});

test("presentation refresh recovers the exact failed view", () => {
  const state = new PresentationRefreshState();

  state.rememberFailure(executive);

  assert.deepEqual(state.failedTarget, executive);
  state.complete(dashboard);
  assert.deepEqual(state.failedTarget, executive);

  state.complete(executive);
  assert.deepEqual(state.failedTarget, undefined);

  state.rememberFailure(executive);
  state.supersede();
  assert.deepEqual(state.failedTarget, undefined);
});

test("stream baselines reconcile after runtime configuration", () => {
  const pending = new BaselineReconciler(false);

  assert.deepEqual(pending.ready(), false);
  assert.deepEqual(pending.configure(), true);
  assert.deepEqual(pending.configure(), false);

  const configured = new BaselineReconciler(true);

  assert.deepEqual(configured.ready(), false);
  assert.deepEqual(configured.ready(true), true);
  assert.deepEqual(configured.configure(), false);
});

test("refresh retries back off and reset after recovery", () => {
  const schedule = new RefreshRetrySchedule([10, 20, 40]);

  assert.deepEqual(
    [schedule.next(), schedule.next(), schedule.next(), schedule.next()],
    [10, 20, 40, 40],
  );
  schedule.reset();
  assert.deepEqual(schedule.next(), 10);
});

test("stale bindings retry until the presentation revision changes", () => {
  const refresh = new StaleBindingRefresh();

  assert.equal(refresh.request("revision-a"), true);
  assert.equal(refresh.request("revision-a"), false);
  assert.equal(refresh.needsRetry("revision-a"), true);
  assert.equal(refresh.needsRetry("revision-b"), false);
  assert.equal(refresh.request("revision-b"), true);
  refresh.clear();
  assert.equal(refresh.needsRetry("revision-b"), false);
});
