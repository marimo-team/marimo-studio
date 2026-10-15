import { cellOutputIsLoading } from "@marimo-studio/marimo-frontend/cell-presentation";
import { useEffect, useLayoutEffect, useRef } from "react";

import type { RenderInputs, RenderReads } from "../renders/inputs.ts";
import type { RuntimeCell } from "./runtime-cell.ts";

import { resolveProjection } from "../projections/resolution.ts";
import { notifyNotebookResults, publishRenderInputReader } from "../renders/inputs.ts";
import { getRuntimeConfig } from "../runtime-config/index.ts";

/**
 * Read a render's values and outputs in this tab, after running the cells
 * its reads depend on. Browser runtimes provide one, and the Server runtime
 * reads render inputs on the server.
 */
export type RuntimeRenderReader = (
  render: string,
  reads: RenderReads,
  signal: AbortSignal,
) => Promise<Pick<RenderInputs, "values" | "outputs">>;

const cellInputs = (reads: RenderReads, cells: readonly RuntimeCell[]): RenderInputs["cells"] => {
  const config = getRuntimeConfig();
  const shown: RenderInputs["cells"] = {};
  for (const request of reads.cells) {
    const resolved = resolveProjection(config, { ...request, kind: "cell" });
    const runtimeCellId = resolved.ok ? resolved.value.runtimeCellId : undefined;
    const output = cells.find((cell) => cell.id === runtimeCellId)?.output;
    if (output) {
      shown[request.target] = { mimetype: output.mimetype, data: output.data };
    }
  }
  return shown;
};

const sameOutputs = (left: readonly unknown[], right: readonly unknown[]): boolean =>
  left.length === right.length && left.every((output, index) => output === right[index]);

/**
 * Tell render hosts when a notebook run settles with new outputs, and publish
 * `read` as the reader of render inputs while the runtime is ready.
 *
 * A read counts only when no cell ran between its start and its end, so one
 * render never mixes results from two runs. Otherwise the reader reports the
 * notebook unsettled, and hosts read again when the run settles.
 */
export const useRenderInputs = (
  cells: readonly RuntimeCell[],
  runtimeReady: boolean,
  read: RuntimeRenderReader | undefined,
): void => {
  const latestCells = useRef(cells);
  const settled = useRef<{ running: boolean; outputs: readonly unknown[] }>(undefined);
  // Advances whenever a cell runs or its output changes.
  const generation = useRef(0);

  useLayoutEffect(() => {
    latestCells.current = cells;
    const running = cells.some((cell) => cellOutputIsLoading(cell.status));
    const previous = settled.current;
    if (
      running ||
      !previous ||
      !sameOutputs(
        previous.outputs,
        cells.map((cell) => cell.output),
      )
    ) {
      generation.current += 1;
    }
  }, [cells]);

  useEffect(() => {
    if (!runtimeReady) {
      settled.current = undefined;
      return;
    }
    const running = cells.some((cell) => cellOutputIsLoading(cell.status));
    const outputs = cells.map((cell) => cell.output);
    const previous = settled.current;
    settled.current = { running, outputs };
    // Cells report console and status changes too. Render hosts care about
    // a finished run, or outputs that changed without one.
    if (running || (previous && !previous.running && sameOutputs(previous.outputs, outputs))) {
      return;
    }
    notifyNotebookResults();
  }, [cells, runtimeReady]);

  useEffect(() => {
    if (!runtimeReady || !read) {
      return;
    }
    return publishRenderInputReader(async (render, reads, signal) => {
      const unsettled = () => latestCells.current.some((cell) => cellOutputIsLoading(cell.status));
      if (unsettled()) {
        return undefined;
      }
      const before = generation.current;
      // Reading runs the cells the reads depend on first, so a first read can
      // span that run and reads again once it settles.
      const { values, outputs } = await read(render, reads, signal);
      const cells = cellInputs(reads, latestCells.current);
      return unsettled() || generation.current !== before ? undefined : { values, outputs, cells };
    });
  }, [read, runtimeReady]);
};
