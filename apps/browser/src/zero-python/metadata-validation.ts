import type { NotebookExport } from "@marimo-team/marimo-export";

import type {
  StudioPreparedContext,
  StudioPreparedManifest,
  StudioProjectionBindings,
} from "./metadata-records.ts";

import { ZeroPythonRuntimeError } from "./errors.ts";

export const validateStudioPreparedManifest = (
  metadata: StudioPreparedManifest,
  context: StudioPreparedContext,
  notebookExport?: NotebookExport,
  expectedInstance?: string,
): void => {
  if (metadata.view !== context.view) {
    invalid(
      `The prepared manifest describes view ${JSON.stringify(metadata.view)} instead of ${JSON.stringify(context.view)}.`,
    );
  }
  if (metadata.planDigest !== context.planDigest) {
    invalid("The prepared projection plan does not match the selected runtime revision.");
  }
  if (expectedInstance !== undefined && metadata.prepared.instance !== expectedInstance) {
    invalid("The prepared export instance does not match the selected runtime instance.");
  }
  validateProjectionBindings(metadata.projections, context.hosts);
  if (notebookExport === undefined) {
    return;
  }
  if (metadata.documentSha256 !== notebookExport.notebook.documentSha256) {
    invalid("The prepared notebook identity does not match the immutable export.");
  }
  const mapped = new Set(projectionEntries(metadata.projections).map((entry) => entry.output));
  if (
    mapped.size !== notebookExport.outputNames.length ||
    notebookExport.outputNames.some((name) => !mapped.has(name))
  ) {
    invalid("The prepared projections do not cover the immutable export output set.");
  }
};

const validateProjectionBindings = (
  projections: StudioProjectionBindings,
  hosts: StudioPreparedContext["hosts"],
): void => {
  const actual = {
    cells: Object.keys(projections.cells).sort(),
    outputs: Object.keys(projections.outputs).sort(),
    values: Object.keys(projections.values).sort(),
  };
  const expected = {
    cells: [...hosts.cells].sort(),
    outputs: [...hosts.outputs].sort(),
    values: [...hosts.values].sort(),
  };
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    invalid("The prepared projections do not cover the authored view hosts.");
  }
};

const projectionEntries = (projections: StudioProjectionBindings) => [
  ...Object.entries(projections.values).map(([host, output]) => ({ host, output, kind: "value" })),
  ...Object.entries(projections.outputs).map(([host, output]) => ({
    host,
    output,
    kind: "output",
  })),
  ...Object.entries(projections.cells).map(([host, output]) => ({ host, output, kind: "cell" })),
];

const invalid = (message: string): never => {
  throw new ZeroPythonRuntimeError("manifest_invalid", message);
};
