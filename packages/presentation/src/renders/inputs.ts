import type { ProjectionRequest } from "@marimo-studio/protocol/projections";
import type { RenderedMedia } from "@marimo-studio/protocol/render";
import type { JsonValue } from "@marimo-studio/protocol/runtime-config";
import type { ProjectDiagnostic } from "@marimo-studio/protocol/view-project";

/** The targets one render reads, as projection requests of its read sites. */
export interface RenderReads {
  readonly revision: string;
  readonly values: readonly ProjectionRequest[];
  readonly outputs: readonly ProjectionRequest[];
  readonly cells: readonly ProjectionRequest[];
}

/**
 * The notebook results a browser runtime computed for one render, keyed by
 * target. A target without a current result is left out.
 */
export interface RenderInputs {
  readonly values: Record<string, JsonValue>;
  readonly outputs: Record<string, RenderedMedia>;
  readonly cells: Record<string, RenderedMedia>;
}

/** A value the notebook computed that a render cannot read. */
export class RenderInputError extends Error {
  constructor(readonly diagnostics: readonly ProjectDiagnostic[]) {
    super(diagnostics.map((item) => item.message).join(" "));
    this.name = "RenderInputError";
  }
}

/**
 * Return the render diagnostic for a failed value read, as the Python runtime
 * reports it. The message comes from the runtime and names the target.
 */
export const valueReadFailure = (code: string, message: string): ProjectDiagnostic => {
  const failure = (renderCode: string, hint: string): ProjectDiagnostic => ({
    code: renderCode,
    severity: "error",
    message,
    hint,
    source: null,
  });
  if (code === "not-json-serializable") {
    return failure(
      "render-value-not-json",
      "Read a table, a dictionary, a list, text, a number, or a date, or select one of its fields.",
    );
  }
  if (code.endsWith("too-large")) {
    return failure(
      "render-values-too-large",
      "Filter or aggregate the value in the notebook, or read one of its fields.",
    );
  }
  return failure("render-input-unavailable", "Run the notebook again, then reload the page.");
};

/**
 * Read a render's inputs from the notebook in this tab, without mounting
 * hosts. Reads use their own owner per render, so they never release or
 * replace the outputs the page's hosts show. Resolves `undefined` while the
 * notebook runs, and hosts read again once the run settles. Rejects with
 * `RenderInputError` for a value the render cannot read.
 */
export type RenderInputReader = (
  render: string,
  reads: RenderReads,
  signal: AbortSignal,
) => Promise<RenderInputs | undefined>;

type Listener = () => void;

let reader: RenderInputReader | undefined;
const listeners = new Set<Listener>();

const notify = (): void => listeners.forEach((listener) => listener());

/**
 * Make `next` the reader render hosts use. Returns a release that clears it
 * unless another runtime has published its own reader since.
 */
export const publishRenderInputReader = (next: RenderInputReader): (() => void) => {
  reader = next;
  notify();
  return () => {
    if (reader === next) {
      reader = undefined;
      notify();
    }
  };
};

export const getRenderInputReader = (): RenderInputReader | undefined => reader;

let preparedState: (() => string | undefined) | undefined;

/**
 * Make `current` the source of the prepared state fingerprint the page shows,
 * which a static export's render hosts look up their bundles by. Returns a
 * release.
 */
export const publishPreparedState = (current: () => string | undefined): (() => void) => {
  preparedState = current;
  notify();
  return () => {
    if (preparedState === current) {
      preparedState = undefined;
      notify();
    }
  };
};

export const getPreparedState = (): (() => string | undefined) | undefined => preparedState;

/**
 * Tell render hosts that the notebook may have new results: a run finished,
 * or the reader selected another prepared state.
 */
export const notifyNotebookResults = (): void => notify();

/** Listen for notebook results and reader changes. Returns an unsubscribe. */
export const subscribeRenderInputs = (listener: Listener): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
