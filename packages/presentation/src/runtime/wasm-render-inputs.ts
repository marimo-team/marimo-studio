import type { OutputReadRequest } from "@marimo-studio/protocol/output-read";

import type { OutputReader } from "../outputs/reader.ts";
import type { ValueReader } from "../values/reader.ts";
import type { RuntimeRenderReader } from "./render-inputs.ts";

import { type RenderInputs, RenderInputError, valueReadFailure } from "../renders/inputs.ts";

interface WasmRenderReaderOptions {
  /** The page's own output consumer, which render reads never use. */
  readonly sessionId: string;
  readonly readValues: ValueReader;
  /** Return an output reader for `consumerId`. */
  readonly readOutputs: (consumerId: string) => OutputReader;
  /** Authorize `request` and run the cells its projections depend on. */
  readonly prepareCells: (request: OutputReadRequest, signal: AbortSignal) => Promise<void>;
}

/**
 * Read a render's values and outputs from the WebAssembly notebook. A value
 * the notebook has not computed, and an output that fails to read, are left
 * out, so the render shows its default for them. A value the render cannot
 * read fails the render.
 *
 * The bridge retains the outputs it formats for a consumer until a read
 * leaves them out. Each render reads outputs as its own consumer, so it never
 * releases the outputs the page's hosts show, and releases its own outputs
 * once it has their bytes.
 */
export const createWasmRenderReader = ({
  sessionId,
  readValues,
  readOutputs,
  prepareCells,
}: WasmRenderReaderOptions): RuntimeRenderReader => {
  const outputReaders = new Map<string, OutputReader>();
  return async (render, reads, signal) => {
    if (reads.cells.length > 0) {
      await prepareCells(
        {
          revision: reads.revision,
          projections: [...reads.cells],
          activeProjections: [...reads.cells],
        },
        signal,
      );
    }
    const values: RenderInputs["values"] = {};
    if (reads.values.length > 0) {
      const read = await readValues(
        {
          revision: reads.revision,
          projections: [...reads.values],
          activeProjections: [...reads.values],
        },
        signal,
      );
      const failures = Object.values(read.errors)
        .filter((error) => error.code !== "value-path-unavailable")
        .map((error) => valueReadFailure(error.code, error.message));
      if (failures.length > 0) {
        throw new RenderInputError(failures);
      }
      for (const [target, value] of Object.entries(read.values)) {
        if (value.codec === "json-v1") {
          values[target] = value.value;
        }
      }
    }
    const outputs: RenderInputs["outputs"] = {};
    if (reads.outputs.length > 0) {
      let reader = outputReaders.get(render);
      if (!reader) {
        reader = readOutputs(`${sessionId}:render:${render}`);
        outputReaders.set(render, reader);
      }
      try {
        const read = await reader(
          {
            revision: reads.revision,
            projections: [...reads.outputs],
            activeProjections: [...reads.outputs],
          },
          signal,
        );
        for (const [target, output] of Object.entries(read.outputs)) {
          outputs[target] = { mimetype: output.mimetype, data: output.data };
        }
      } finally {
        await reader(
          { revision: reads.revision, projections: [], activeProjections: [] },
          new AbortController().signal,
        ).catch(() => undefined);
      }
    }
    return { values, outputs };
  };
};
