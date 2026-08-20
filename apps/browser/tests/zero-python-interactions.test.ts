import type { JsonObject, NotebookExport } from "@marimo-team/marimo-export";
import type { PreparedPublication, PreparedStatePort } from "@marimo-team/marimo-export/prepared";

import { PreparedStateController } from "@marimo-team/marimo-export/prepared";
import { expect, it, vi } from "vite-plus/test";

import { StudioPreparedInteractions } from "../src/zero-python/interactions.ts";
import { notebookExportFixture } from "./zero-python-fixture.ts";

const publication = (notebookExport: NotebookExport, inputs: JsonObject): PreparedPublication => {
  const state = notebookExport.resolve(inputs);
  return Object.freeze({
    manifest: Object.freeze({
      schema: "marimo-export.prepared.v1",
      instance: notebookExport.identity,
      exportUrl: notebookExport.base.href,
      inputs: state.inputs,
      stateFingerprint: state.fingerprint,
      refreshIntervalMs: 0,
    }),
    notebookExport,
    state,
  });
};

it("selects a pending peer control request after publication refresh", async () => {
  const binding = { input: "scale", path: [] } as const;
  const first = notebookExportFixture({
    identity: "1".repeat(64),
    inputs: [{ scale: 3 }],
    controlBindings: { "prepared-scale": binding },
  });
  const refreshed = notebookExportFixture({
    identity: "2".repeat(64),
    inputs: [{ scale: 3 }, { scale: 1 }],
    controlBindings: { "prepared-scale": binding },
  });
  const restore = vi.fn<NonNullable<PreparedStatePort["restore"]>>(async () => {});
  const state = new PreparedStateController({ async apply() {}, restore });
  await state.start(publication(first, { scale: 3 }));
  const interactions = new StudioPreparedInteractions(state, () => false);

  interactions.controlInput({ objectId: "prepared-scale", value: 1 }, true);
  await vi.waitFor(() => expect(state.snapshot().pendingInputs).toEqual({ scale: 1 }));

  expect(state.snapshot().current?.state.inputs).toEqual({ scale: 3 });
  expect(restore).toHaveBeenCalledOnce();

  await state.replacePublication(publication(refreshed, { scale: 3 }));

  expect(state.snapshot().current?.notebookExport).toBe(refreshed);
  expect(state.snapshot().current?.state.inputs).toEqual({ scale: 1 });
  expect(state.snapshot().pendingInputs).toBeUndefined();
  await state.dispose();
});
