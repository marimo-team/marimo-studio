import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  BaselineReconciler,
  RefreshRetrySchedule,
  sameShellPresentation,
  ShellRefreshState,
} from "../src/document/refresh-state.ts";

const dashboard = {
  documentUrl: "/studio/dashboard/",
  supportUrl: "/_marimo-studio/views/dashboard",
};
const executive = {
  documentUrl: "/studio/executive/",
  supportUrl: "/_marimo-studio/views/executive",
};

test("unchanged presentation revisions preserve the current shell", () => {
  const current = { ...dashboard, revision: "same" };

  assert.deepEqual(sameShellPresentation(current, { ...current }), true);
  assert.deepEqual(sameShellPresentation(current, { ...current, revision: "changed" }), false);
  assert.deepEqual(sameShellPresentation(current, { ...current, documentUrl: "/other/" }), false);
  assert.deepEqual(
    sameShellPresentation(current, {
      ...current,
      supportUrl: "/_marimo-studio/views/other",
    }),
    false,
  );
});

test("shell changes recover the exact failed view", () => {
  const state = new ShellRefreshState();

  state.rememberFailure(executive);

  assert.deepEqual(state.failedTarget, executive);
  assert.deepEqual(state.targetForChange("runtime", dashboard), executive);
  assert.deepEqual(state.targetForChange("css", dashboard), executive);
  assert.deepEqual(state.pending, true);

  state.complete(dashboard);
  assert.deepEqual(state.targetForChange("runtime", dashboard), executive);

  state.complete(executive);
  assert.deepEqual(state.failedTarget, undefined);
  assert.deepEqual(state.targetForChange("runtime", dashboard), dashboard);
  assert.deepEqual(state.targetForChange("views", dashboard), undefined);
  assert.deepEqual(state.targetForChange("css", dashboard), undefined);
  assert.deepEqual(state.pending, false);

  state.rememberFailure(executive);
  state.supersede();
  assert.deepEqual(state.targetForChange("runtime", dashboard), dashboard);
});

test("stream baselines reconcile after runtime configuration", () => {
  const pending = new BaselineReconciler(false);

  assert.deepEqual(pending.ready(), false);
  assert.deepEqual(pending.configure(), true);
  assert.deepEqual(pending.configure(), false);

  const configured = new BaselineReconciler(true);

  assert.deepEqual(configured.ready(), true);
  assert.deepEqual(configured.ready(), true);
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
