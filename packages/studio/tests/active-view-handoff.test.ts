import { afterEach, expect, it, vi } from "vite-plus/test";

import {
  createActiveViewHandoffRemote,
  stageCommittedView,
} from "../src/app/active-view-handoff.ts";
import { ViewTransition } from "../src/features/views/transition.ts";
import { deferred, type JsonFetch } from "./agent-remote-test-support.ts";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("rolls back an uncommitted active-view handoff with the same ownership id", async () => {
  const fetch = vi.fn<JsonFetch>(async () => new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  const remote = createActiveViewHandoffRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );

  const handoff = remote.stage("dashboard", "report");
  expect(await handoff.ready).toBe(true);
  await handoff.rollback();

  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch).toHaveBeenLastCalledWith(
    expect.anything(),
    expect.objectContaining({ method: "DELETE" }),
  );
  expect(fetch.mock.calls[0]?.[0]).toBe(fetch.mock.calls[1]?.[0]);
  expect(JSON.parse(fetch.mock.calls[0]![1].body)).toEqual({
    schema: 1,
    clientId: "browser-client-1234",
    fromView: "dashboard",
    toView: "report",
  });
});

it("leaves a committed active-view handoff for stream promotion", async () => {
  const fetch = vi.fn<JsonFetch>(async () => new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  const remote = createActiveViewHandoffRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );

  const handoff = remote.stage("dashboard", "report");
  expect(await handoff.ready).toBe(true);
  handoff.commit();
  await handoff.rollback();

  expect(fetch).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[0]?.[1].method).toBe("POST");
});

it("rolls back a handoff whose owner aborts during acquisition", async () => {
  const fetch = vi.fn<JsonFetch>((_url, init) => {
    if (init.method === "DELETE") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener("abort", () =>
        reject(new DOMException("Aborted", "AbortError")),
      );
    });
  });
  vi.stubGlobal("fetch", fetch);
  const recover = vi.fn(async () => undefined);
  const remote = createActiveViewHandoffRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
    recover,
  );
  const owner = new AbortController();
  const handoff = remote.stage("dashboard", "report", owner.signal);
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce());

  owner.abort();
  await expect(handoff.ready).rejects.toMatchObject({ name: "AbortError" });
  await handoff.rollback();

  expect(fetch).toHaveBeenLastCalledWith(
    expect.anything(),
    expect.objectContaining({ method: "DELETE" }),
  );
  expect(recover).toHaveBeenCalledOnce();
});

it("releases view ownership when preview rollback fails", async () => {
  const previewFailure = new Error("preview rollback failed");
  const fetch = vi.fn<JsonFetch>(async () => new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  const handoff = createActiveViewHandoffRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );
  const previewRollback = vi.fn(async () => {
    throw previewFailure;
  });
  const staged = stageCommittedView(
    { ready: Promise.resolve(true), rollback: previewRollback },
    () => handoff.stage("dashboard", "report"),
  );
  expect(await staged.ready).toBe(true);

  const first = staged.rollback();
  const second = staged.rollback();
  await expect(first).rejects.toBe(previewFailure);
  await expect(second).rejects.toBe(previewFailure);

  expect(first).toBe(second);
  expect(previewRollback).toHaveBeenCalledOnce();
  expect(fetch).toHaveBeenLastCalledWith(
    expect.anything(),
    expect.objectContaining({ method: "DELETE" }),
  );
});

it("attempts preview rollback when ownership release fails", async () => {
  const ownershipFailure = new Error("ownership rollback failed");
  const previewRollback = vi.fn(async () => undefined);
  const ownershipRollback = vi.fn(async () => {
    throw ownershipFailure;
  });
  const staged = stageCommittedView(
    { ready: Promise.resolve(true), rollback: previewRollback },
    () => ({
      ready: Promise.resolve(true),
      commit: vi.fn(),
      rollback: ownershipRollback,
    }),
  );
  expect(await staged.ready).toBe(true);

  await expect(staged.rollback()).rejects.toBe(ownershipFailure);

  expect(previewRollback).toHaveBeenCalledOnce();
  expect(ownershipRollback).toHaveBeenCalledOnce();
});

it("aggregates preview and ownership rollback failures", async () => {
  const previewFailure = new Error("preview rollback failed");
  const ownershipFailure = new Error("ownership rollback failed");
  const previewRollback = vi.fn(async () => {
    throw previewFailure;
  });
  const ownershipRollback = vi.fn(async () => {
    throw ownershipFailure;
  });
  const staged = stageCommittedView(
    { ready: Promise.resolve(true), rollback: previewRollback },
    () => ({
      ready: Promise.resolve(true),
      commit: vi.fn(),
      rollback: ownershipRollback,
    }),
  );
  expect(await staged.ready).toBe(true);

  const rollback = staged.rollback();
  await expect(rollback).rejects.toBeInstanceOf(AggregateError);
  await expect(rollback).rejects.toMatchObject({
    errors: [ownershipFailure, previewFailure],
  });

  expect(previewRollback).toHaveBeenCalledOnce();
  expect(ownershipRollback).toHaveBeenCalledOnce();
});

it("starts preview restoration before ownership release and awaits it afterward", async () => {
  const released = deferred<Response>();
  const previewReady = deferred<void>();
  const events: string[] = [];
  const fetch = vi.fn<JsonFetch>((_url, init) => {
    if (init.method === "POST") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    events.push("delete-started");
    return released.promise.then((response) => {
      events.push("delete-completed");
      return response;
    });
  });
  vi.stubGlobal("fetch", fetch);
  const remote = createActiveViewHandoffRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );
  const previewRollback = vi.fn(async () => {
    events.push("preview-started");
    await previewReady.promise;
    events.push("preview-ready");
  });
  const staged = stageCommittedView(
    { ready: Promise.resolve(true), rollback: previewRollback },
    () => remote.stage("dashboard", "report"),
  );
  expect(await staged.ready).toBe(true);

  const rollback = staged.rollback();
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(previewRollback).toHaveBeenCalledOnce();
  expect(events).toEqual(["preview-started", "delete-started"]);

  released.resolve(new Response(null, { status: 204 }));
  await vi.waitFor(() => expect(events).toContain("delete-completed"));
  let settled = false;
  const settling = Promise.resolve(rollback).then(() => {
    settled = true;
  });
  await Promise.resolve();
  expect(settled).toBe(false);

  previewReady.resolve();
  await settling;

  expect(events).toEqual([
    "preview-started",
    "delete-started",
    "delete-completed",
    "preview-ready",
  ]);
  remote.dispose();
});

it("holds the next transition until ownership release reaches a terminal response", async () => {
  vi.useFakeTimers();
  const terminalRelease = deferred<Response>();
  let deleteAttempts = 0;
  const fetch = vi.fn<JsonFetch>((_url, init) => {
    if (init.method === "POST") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    deleteAttempts += 1;
    if (deleteAttempts === 1) {
      return Promise.reject(new TypeError("connection reset"));
    }
    if (deleteAttempts === 2) {
      return Promise.resolve(new Response(null, { status: 503 }));
    }
    if (deleteAttempts === 3) {
      return new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("Timed out", "TimeoutError")),
        );
      });
    }
    return terminalRelease.promise;
  });
  vi.stubGlobal("fetch", fetch);
  const remote = createActiveViewHandoffRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );
  const stagedViews: string[] = [];
  const transition = new ViewTransition("dashboard", {
    prepare: async () => true,
    stage(view) {
      stagedViews.push(view);
      const preview = { ready: Promise.resolve(true), rollback: async () => undefined };
      return view === "report"
        ? stageCommittedView(preview, () => remote.stage("dashboard", "report"))
        : preview;
    },
    commit: (view) => view !== "report",
    cancel() {},
  });

  const report = transition.select("report", "preserve");
  await vi.waitFor(() => expect(deleteAttempts).toBe(1));
  const story = transition.select("story", "preserve");
  expect(stagedViews).toEqual(["report"]);

  for (let timerWave = 0; timerWave < 4 && deleteAttempts < 4; timerWave += 1) {
    await vi.runOnlyPendingTimersAsync();
  }
  expect(deleteAttempts).toBe(4);
  expect(stagedViews).toEqual(["report"]);

  terminalRelease.resolve(new Response(null, { status: 204 }));
  await expect(report).resolves.toBe(false);
  await expect(story).resolves.toBe(true);
  expect(stagedViews).toEqual(["report", "story"]);
  remote.dispose();
});

it("recovers the committed view after a stale-owner release conflict", async () => {
  const fetch = vi.fn<JsonFetch>(
    async (_url, init) => new Response(null, { status: init.method === "POST" ? 204 : 409 }),
  );
  vi.stubGlobal("fetch", fetch);
  const recover = vi.fn(async () => undefined);
  const remote = createActiveViewHandoffRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
    recover,
  );
  const handoff = remote.stage("dashboard", "report");
  expect(await handoff.ready).toBe(true);

  await expect(handoff.rollback()).resolves.toBeUndefined();

  expect(recover).toHaveBeenCalledOnce();
  expect(recover).toHaveBeenCalledWith("dashboard", expect.any(AbortSignal));
  remote.dispose();
});

it("recovers after rejected acquisition even when cleanup reports no owner", async () => {
  const fetch = vi.fn<JsonFetch>(
    async (_url, init) => new Response(null, { status: init.method === "POST" ? 409 : 204 }),
  );
  vi.stubGlobal("fetch", fetch);
  const recover = vi.fn(async () => undefined);
  const remote = createActiveViewHandoffRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
    recover,
  );
  const handoff = remote.stage("dashboard", "report");

  await expect(handoff.ready).rejects.toThrow(
    "Active view ownership could not be handed off (409).",
  );
  await expect(handoff.rollback()).resolves.toBeUndefined();

  expect(recover).toHaveBeenCalledOnce();
  expect(recover).toHaveBeenCalledWith("dashboard", expect.any(AbortSignal));
  remote.dispose();
});

it("propagates nonretryable ownership release responses", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn<JsonFetch>(
    async (_url, init) => new Response(null, { status: init.method === "POST" ? 204 : 403 }),
  );
  vi.stubGlobal("fetch", fetch);
  const remote = createActiveViewHandoffRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );
  const handoff = remote.stage("dashboard", "report");
  expect(await handoff.ready).toBe(true);

  await expect(handoff.rollback()).rejects.toThrow(
    "Active view ownership could not be released (403).",
  );
  await vi.runAllTimersAsync();

  remote.dispose();
});

it("service disposal cancels ownership reconciliation without another retry", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn<JsonFetch>((_url, init) => {
    if (init.method === "POST") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener("abort", () =>
        reject(new DOMException("Aborted", "AbortError")),
      );
    });
  });
  vi.stubGlobal("fetch", fetch);
  const remote = createActiveViewHandoffRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );
  const handoff = remote.stage("dashboard", "report");
  expect(await handoff.ready).toBe(true);
  const rollback = handoff.rollback();
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));

  remote.dispose();
  await expect(rollback).resolves.toBeUndefined();
  await vi.runAllTimersAsync();
  await expect(handoff.rollback()).resolves.toBeUndefined();

  expect(fetch).toHaveBeenCalledTimes(2);
});
