import type { OutputReadRequest, OutputReadResponse } from "@marimo-studio/protocol/output-read";

import { expect, test, vi } from "vite-plus/test";

import type { OutputReader } from "../src/outputs/reader.ts";

import { OutputOwnerReconciler } from "../src/runtime/outputs/output-owner-reconciler.ts";
import { createBatchedOutputReader } from "../src/runtime/outputs/output-read-batcher.ts";
import { projectionRequest } from "./runtime-fixtures.ts";

const request = (targets: string[]): OutputReadRequest => ({
  revision: "presentation-revision",
  projections: targets.map((target) => projectionRequest(target, "output")),
  activeProjections: targets.map((target) => projectionRequest(target, "output")),
});

const rendered = (data: string) => ({
  ownerCellId: "projected-owner",
  mimetype: "text/plain",
  data,
  timestamp: 1,
  resetUiObjectIds: [],
});

test("an aggregate overflow falls back to individually bounded output reads", async () => {
  const data = "x".repeat(600_000);
  const overlays = { inspector: rendered("inspector") };
  const source = vi.fn<OutputReader>(async (read): Promise<OutputReadResponse> => {
    if (read.projections.length > 1) {
      return {
        outputs: {},
        errors: {
          "*": {
            code: "response-too-large",
            message: "The output response exceeds the aggregate byte limit.",
          },
        },
      };
    }
    const target = read.projections[0]!.target;
    return { outputs: { [target]: rendered(data) }, errors: {}, overlays };
  });
  const batched = createBatchedOutputReader(source);
  const active = request(["report", "figure"]).activeProjections;
  const report = batched({ ...request(["report"]), activeProjections: active });
  const figure = batched({ ...request(["figure"]), activeProjections: active });

  const [reportResponse, figureResponse] = await Promise.all([report, figure]);

  expect(source).toHaveBeenCalledTimes(3);
  expect(reportResponse.outputs.report?.data).toHaveLength(600_000);
  expect(reportResponse.outputs.figure?.data).toHaveLength(600_000);
  expect(figureResponse).toEqual(reportResponse);
  expect(reportResponse.overlays).toEqual(overlays);
});

test("disjoint active snapshots remain separate bounded reads", async () => {
  const source = vi.fn<OutputReader>().mockResolvedValue({ outputs: {}, errors: {} });
  const batched = createBatchedOutputReader(source);
  const left = Array.from({ length: 100 }, (_, index) => `left-${index}`);
  const right = Array.from({ length: 100 }, (_, index) => `right-${index}`);

  await Promise.all([batched(request(left)), batched(request(right))]);

  expect(source).toHaveBeenCalledTimes(2);
  expect(source.mock.calls.map(([read]) => read.activeProjections.length)).toEqual([100, 100]);
});

test("a retired batch does not dispatch after an earlier ownership read", async () => {
  let releaseFirst = (_response: OutputReadResponse) => {};
  const firstResponse = new Promise<OutputReadResponse>((resolve) => {
    releaseFirst = resolve;
  });
  const source = vi
    .fn<OutputReader>()
    .mockImplementationOnce(() => firstResponse)
    .mockResolvedValue({ outputs: {}, errors: {} });
  const reconciler = new OutputOwnerReconciler(source);
  const owned: OutputReader = (read, signal) => reconciler.read("a".repeat(64), read, signal);
  const first = owned(request(["first"]));
  await vi.waitFor(() => expect(source).toHaveBeenCalledOnce());

  const batched = createBatchedOutputReader(owned);
  const reportController = new AbortController();
  const figureController = new AbortController();
  const report = batched(request(["report"]), reportController.signal);
  const figure = batched(request(["figure"]), figureController.signal);
  await Promise.resolve();
  reportController.abort();
  figureController.abort();

  await expect(report).rejects.toMatchObject({ name: "AbortError" });
  await expect(figure).rejects.toMatchObject({ name: "AbortError" });
  releaseFirst({ outputs: {}, errors: {} });
  await first;
  await Promise.resolve();
  await Promise.resolve();

  expect(source).toHaveBeenCalledOnce();
  reconciler.dispose();
});
