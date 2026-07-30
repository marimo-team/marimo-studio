import { assertEquals } from "@std/assert";

import {
  BaselineReconciler,
  ShellChangeQueue,
  ShellRefreshState,
} from "../src/shell-refresh-state.ts";

const dashboard = {
  documentUrl: "/studio/dashboard/",
  supportUrl: "/_marimo-studio/views/dashboard",
};
const executive = {
  documentUrl: "/studio/executive/",
  supportUrl: "/_marimo-studio/views/executive",
};

Deno.test("shell changes recover the exact failed view", () => {
  const state = new ShellRefreshState();

  state.rememberFailure(executive);

  assertEquals(state.targetForChange("runtime", dashboard), executive);
  assertEquals(state.targetForChange("views", dashboard), executive);
  assertEquals(state.targetForChange("html", dashboard), executive);
  assertEquals(state.targetForChange("css", dashboard), executive);
  assertEquals(state.pending, true);

  state.complete(dashboard);
  assertEquals(state.targetForChange("runtime", dashboard), executive);

  state.rememberFailure(dashboard);
  state.complete(executive);
  assertEquals(state.targetForChange("runtime", executive), dashboard);

  state.complete(dashboard);
  assertEquals(state.targetForChange("runtime", dashboard), dashboard);
  assertEquals(state.targetForChange("views", dashboard), undefined);
  assertEquals(state.targetForChange("css", dashboard), undefined);
  assertEquals(state.pending, false);

  state.rememberFailure(executive);
  state.supersede();
  assertEquals(state.targetForChange("runtime", dashboard), dashboard);
});

Deno.test("queued changes keep the highest-priority refresh", () => {
  const queue = new ShellChangeQueue();
  queue.push("css");
  queue.push("views");
  queue.push("runtime");

  assertEquals(queue.take(), "runtime");

  queue.push("runtime");
  queue.push("html");
  queue.push("views");

  assertEquals(queue.take(), "html");
  assertEquals(queue.take(), undefined);
});

Deno.test("stream baselines reconcile after runtime configuration", () => {
  const pending = new BaselineReconciler(false);

  assertEquals(pending.ready(), false);
  assertEquals(pending.configure(), true);
  assertEquals(pending.configure(), false);

  const configured = new BaselineReconciler(true);

  assertEquals(configured.ready(), true);
  assertEquals(configured.ready(), true);
});
