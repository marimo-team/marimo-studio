import { expect, it, vi } from "vite-plus/test";

import type {
  MutationAcknowledgementPort,
  NotebookMutationCompletion,
  NotebookMutationEffects,
} from "../src/features/preview/notebook-mutation-coordinator.ts";

import { NotebookMutationCoordinator } from "../src/features/preview/notebook-mutation-coordinator.ts";

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

const acknowledgement = () => ({
  close: vi.fn<MutationAcknowledgementPort["close"]>(),
  postMessage: vi.fn<MutationAcknowledgementPort["postMessage"]>(),
});

const admit = async (coordinator: NotebookMutationCoordinator, generation: number) => {
  const port = acknowledgement();
  coordinator.admit(generation, port);
  await vi.waitFor(() => expect(port.postMessage).toHaveBeenCalledOnce());
};

const setup = () => {
  const owner = {};
  const unchanged = vi.fn();
  const effects: NotebookMutationEffects = {
    gate: vi.fn(async () => ({ owner, complete: unchanged })),
    markCachedViewsStale: vi.fn(),
    resetActive: vi.fn(),
    saveFailed: vi.fn(),
    transactionFailed: vi.fn(),
  };
  return { coordinator: new NotebookMutationCoordinator(effects), effects, owner, unchanged };
};

it("coalesces duplicate admission and claims one reconciliation", async () => {
  const { coordinator, effects } = setup();
  const first = acknowledgement();
  const duplicate = acknowledgement();

  coordinator.admit(2, first);
  coordinator.admit(2, duplicate);
  await vi.waitFor(() => expect(first.postMessage).toHaveBeenCalledOnce());
  await vi.waitFor(() => expect(duplicate.postMessage).toHaveBeenCalledOnce());

  expect(effects.gate).toHaveBeenCalledTimes(1);
  coordinator.transactionApplied(2, true);
  expect(coordinator.saved(2)).toBe(true);
  expect(coordinator.saved(2)).toBe(false);
  expect(coordinator.buildCompleted(1, vi.fn())).toBe(false);
  expect(coordinator.pending).toBe(true);
  const completed = vi.fn();
  expect(coordinator.buildCompleted(2, completed)).toBe(true);
  expect(completed).toHaveBeenCalledOnce();
  expect(coordinator.pending).toBe(false);
});

it("settles one unchanged transaction without a save or build", async () => {
  const { coordinator, unchanged } = setup();
  await admit(coordinator, 1);

  coordinator.transactionApplied(1, false);

  expect(coordinator.pending).toBe(false);
  expect(unchanged).toHaveBeenCalledOnce();
});

it("coalesces unchanged completions for one admission owner", async () => {
  const { coordinator, unchanged } = setup();
  await admit(coordinator, 1);
  await admit(coordinator, 2);

  coordinator.transactionApplied(1, false);
  coordinator.transactionApplied(2, false);

  expect(coordinator.pending).toBe(false);
  expect(unchanged).toHaveBeenCalledOnce();
});

it.each([
  { name: "unchanged then changed", firstChanged: false },
  { name: "changed then unchanged", firstChanged: true },
])(
  "runs the authoritative build before a same-owner $name completion",
  async ({ firstChanged }) => {
    const events: string[] = [];
    const owner = {};
    const effects: NotebookMutationEffects = {
      gate: vi.fn(async (generation) => ({
        owner,
        complete: () => events.push(`unchanged-${generation}`),
      })),
      markCachedViewsStale: vi.fn(),
      resetActive: vi.fn(),
      saveFailed: vi.fn(),
      transactionFailed: vi.fn(),
    };
    const coordinator = new NotebookMutationCoordinator(effects);
    await admit(coordinator, 1);
    await admit(coordinator, 2);

    coordinator.transactionApplied(1, firstChanged);
    coordinator.transactionApplied(2, !firstChanged);
    coordinator.saved(firstChanged ? 1 : 2);
    coordinator.buildCompleted(firstChanged ? 1 : 2, () => events.push("build"));

    expect(events).toEqual(["build", `unchanged-${firstChanged ? 2 : 1}`]);
    expect(coordinator.pending).toBe(false);
  },
);

it("settles unchanged work for a new view after an older view build", async () => {
  const dashboard = {};
  const report = {};
  const events: string[] = [];
  const effects: NotebookMutationEffects = {
    gate: vi.fn(async (generation) => ({
      owner: generation === 1 ? dashboard : report,
      complete: () => events.push(generation === 1 ? "dashboard-unchanged" : "report-unchanged"),
    })),
    markCachedViewsStale: vi.fn(),
    resetActive: vi.fn(),
    saveFailed: vi.fn(),
    transactionFailed: vi.fn(),
  };
  const coordinator = new NotebookMutationCoordinator(effects);
  await admit(coordinator, 1);
  await admit(coordinator, 2);
  coordinator.transactionApplied(1, true);
  coordinator.transactionApplied(2, false);
  coordinator.saved(1);

  coordinator.buildCompleted(1, () => events.push("dashboard-build"));

  expect(events).toEqual(["dashboard-build", "report-unchanged"]);
  expect(coordinator.pending).toBe(false);
});

it("rolls back a failed transaction so the same generation can retry", async () => {
  const { coordinator, effects } = setup();
  const first = acknowledgement();
  coordinator.admit(3, first);
  await vi.waitFor(() => expect(first.postMessage).toHaveBeenCalledOnce());

  coordinator.transactionFailed(3);
  const retry = acknowledgement();
  coordinator.admit(3, retry);
  await vi.waitFor(() => expect(retry.postMessage).toHaveBeenCalledOnce());

  expect(effects.transactionFailed).toHaveBeenCalledWith(3);
  expect(effects.gate).toHaveBeenCalledTimes(2);
});

it("keeps an earlier mutation fenced when a later transaction fails", async () => {
  const { coordinator, effects } = setup();
  const first = acknowledgement();
  coordinator.admit(1, first);
  await vi.waitFor(() => expect(first.postMessage).toHaveBeenCalledOnce());
  coordinator.transactionApplied(1, true);
  const second = acknowledgement();
  coordinator.admit(2, second);
  await vi.waitFor(() => expect(second.postMessage).toHaveBeenCalledOnce());

  coordinator.transactionFailed(2);
  expect(coordinator.pending).toBe(true);
  expect(effects.transactionFailed).toHaveBeenCalledWith(2);
  expect(coordinator.saved(1)).toBe(true);
  expect(coordinator.buildCompleted(1, vi.fn())).toBe(false);

  const retry = acknowledgement();
  coordinator.admit(2, retry);
  await vi.waitFor(() => expect(retry.postMessage).toHaveBeenCalledOnce());
  coordinator.transactionApplied(2, true);
  expect(coordinator.saved(2)).toBe(true);
  expect(coordinator.buildCompleted(2, vi.fn())).toBe(true);
  expect(coordinator.pending).toBe(false);
});

it("keeps a failed save fenced until retry and exact build completion", async () => {
  const { coordinator, effects } = setup();
  const port = acknowledgement();
  coordinator.admit(4, port);
  await vi.waitFor(() => expect(port.postMessage).toHaveBeenCalledOnce());
  coordinator.transactionApplied(4, true);

  coordinator.saveFailed(4);
  expect(effects.saveFailed).toHaveBeenCalledWith(4);
  expect(coordinator.pending).toBe(true);
  expect(coordinator.saved(4)).toBe(true);
  coordinator.saveFailed(4);
  expect(effects.saveFailed).toHaveBeenCalledOnce();
  expect(coordinator.buildCompleted(3, vi.fn())).toBe(false);
  expect(coordinator.buildCompleted(4, vi.fn())).toBe(true);
});

it("keeps authoritative save completion after a late transaction failure", async () => {
  const { coordinator, effects } = setup();
  const port = acknowledgement();
  coordinator.admit(7, port);
  await vi.waitFor(() => expect(port.postMessage).toHaveBeenCalledOnce());
  expect(coordinator.saved(7)).toBe(true);
  const completed = vi.fn();
  expect(coordinator.buildCompleted(7, completed)).toBe(true);
  expect(completed).toHaveBeenCalledOnce();

  coordinator.transactionFailed(7);
  expect(effects.transactionFailed).not.toHaveBeenCalled();
  expect(coordinator.pending).toBe(false);
});

it("lets a newer save subsume older success and failure messages", async () => {
  const { coordinator, effects } = setup();
  for (const generation of [8, 9]) {
    const port = acknowledgement();
    coordinator.admit(generation, port);
    await vi.waitFor(() => expect(port.postMessage).toHaveBeenCalledOnce());
    coordinator.transactionApplied(generation, true);
  }

  expect(coordinator.saved(9)).toBe(true);
  expect(coordinator.saved(8)).toBe(false);
  coordinator.saveFailed(8);
  expect(effects.saveFailed).not.toHaveBeenCalled();
  expect(coordinator.buildCompleted(9, vi.fn())).toBe(true);
});

it("uses an authoritative full save when the applied message is lost", async () => {
  const { coordinator, effects } = setup();
  const port = acknowledgement();
  coordinator.admit(10, port);
  await vi.waitFor(() => expect(port.postMessage).toHaveBeenCalledOnce());

  expect(coordinator.saved(10)).toBe(true);
  coordinator.transactionFailed(10);
  expect(effects.transactionFailed).not.toHaveBeenCalled();
  const completed = vi.fn();
  expect(coordinator.buildCompleted(10, completed)).toBe(true);
  expect(completed).toHaveBeenCalledOnce();
  expect(coordinator.pending).toBe(false);
});

it("terminalizes the old admission when the editor reloads", async () => {
  const gate = deferred<NotebookMutationCompletion>();
  const owner = {};
  const effects: NotebookMutationEffects = {
    gate: vi.fn(() => gate.promise),
    markCachedViewsStale: vi.fn(),
    resetActive: vi.fn(),
    saveFailed: vi.fn(),
    transactionFailed: vi.fn(),
  };
  const coordinator = new NotebookMutationCoordinator(effects);
  const port = acknowledgement();
  coordinator.admit(5, port);

  expect(coordinator.editorReloaded()).toBe(true);
  gate.resolve({ owner, complete: vi.fn() });
  await vi.waitFor(() =>
    expect(port.postMessage).toHaveBeenCalledWith({
      schema: 1,
      type: "marimo-studio:editor-document-mutation-failed",
      generation: 5,
    }),
  );
  expect(effects.markCachedViewsStale).toHaveBeenCalledOnce();
  expect(effects.resetActive).toHaveBeenCalledOnce();
});

it("preserves preview ownership when the editor reloads without a pending mutation", () => {
  const { coordinator, effects } = setup();

  expect(coordinator.editorReloaded()).toBe(false);

  expect(effects.markCachedViewsStale).not.toHaveBeenCalled();
  expect(effects.resetActive).not.toHaveBeenCalled();
});

it("rejects a tagged build completion from an earlier editor document", async () => {
  const { coordinator } = setup();
  const port = acknowledgement();
  coordinator.admit(1, port);
  await vi.waitFor(() => expect(port.postMessage).toHaveBeenCalledOnce());
  coordinator.editorReloaded();
  const stale = vi.fn();

  expect(coordinator.buildCompleted(1, stale)).toBe(false);
  expect(stale).not.toHaveBeenCalled();

  const ordinary = vi.fn();
  expect(coordinator.buildCompleted(undefined, ordinary)).toBe(true);
  expect(ordinary).toHaveBeenCalledOnce();
});

it("starts a fresh generation namespace after reloading a saved mutation", async () => {
  const { coordinator, effects } = setup();
  const old = acknowledgement();
  coordinator.admit(5, old);
  await vi.waitFor(() => expect(old.postMessage).toHaveBeenCalledOnce());
  expect(coordinator.saved(5)).toBe(true);

  expect(coordinator.editorReloaded()).toBe(true);
  expect(coordinator.pending).toBe(false);
  expect(effects.resetActive).toHaveBeenCalledOnce();

  const fresh = acknowledgement();
  coordinator.admit(1, fresh);
  await vi.waitFor(() => expect(fresh.postMessage).toHaveBeenCalledOnce());
  expect(coordinator.saved(1)).toBe(true);
  expect(coordinator.buildCompleted(1, vi.fn())).toBe(true);
});

it("ignores an older save failure after success claimed reconciliation", async () => {
  const { coordinator, effects } = setup();
  const port = acknowledgement();
  coordinator.admit(6, port);
  await vi.waitFor(() => expect(port.postMessage).toHaveBeenCalledOnce());

  expect(coordinator.saved(6)).toBe(true);
  coordinator.saveFailed(6);
  expect(effects.saveFailed).not.toHaveBeenCalled();
});
