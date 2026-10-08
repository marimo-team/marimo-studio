import type { ProjectionRequest } from "./projections.ts";
import type { JsonValue } from "./runtime-config.ts";

/** A notebook output or a cell's output as marimo shows it. */
export interface RenderedMedia {
  readonly mimetype: string;
  readonly data: JsonValue;
}

/**
 * The body a document view posts to its `render` support route. The Server
 * runtime names the projections Studio reads from the kernel and session. The
 * other runtimes post the values, outputs, and cells their hosts show.
 */
export type DocumentRenderRequest =
  | {
      readonly revision: string;
      readonly valueProjections: readonly ProjectionRequest[];
      readonly outputProjections: readonly ProjectionRequest[];
      readonly cellProjections: readonly ProjectionRequest[];
      readonly values?: never;
      readonly outputs?: never;
      readonly cells?: never;
    }
  | {
      readonly revision: string;
      readonly values: Record<string, JsonValue>;
      readonly outputs: Record<string, RenderedMedia>;
      readonly cells: Record<string, RenderedMedia>;
      readonly valueProjections?: never;
      readonly outputProjections?: never;
      readonly cellProjections?: never;
    };
