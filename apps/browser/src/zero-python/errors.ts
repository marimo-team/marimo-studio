import { isNotebookExportError } from "@marimo-team/marimo-export";
import { isPreparedExportError } from "@marimo-team/marimo-export/prepared";
import { z } from "zod";

export interface ZeroPythonRuntimeErrorOptions {
  readonly cause?: unknown;
}

const runtimeFailureSchema = z.instanceof(Error);
type UnparsedRuntimeFailure = Parameters<typeof runtimeFailureSchema.safeParse>[0];

export class ZeroPythonRuntimeError extends Error {
  constructor(
    readonly code: string,
    message: string,
    options: ZeroPythonRuntimeErrorOptions = {},
  ) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "ZeroPythonRuntimeError";
  }
}

export const isZeroPythonQueryUnavailable = (error: UnparsedRuntimeFailure): boolean =>
  (isPreparedExportError(error) &&
    (error.code === "query_miss" || error.code === "query_ambiguous")) ||
  (isNotebookExportError(error) && error.code === "state_unavailable");

export const zeroPythonFailure = (error: UnparsedRuntimeFailure): ZeroPythonRuntimeError => {
  if (error instanceof ZeroPythonRuntimeError) {
    return error;
  }
  if (isPreparedExportError(error)) {
    return new ZeroPythonRuntimeError(error.code, error.message, { cause: error });
  }
  if (isNotebookExportError(error)) {
    return new ZeroPythonRuntimeError(`export_${error.code}`, error.message, { cause: error });
  }
  const parsed = runtimeFailureSchema.safeParse(error);
  return new ZeroPythonRuntimeError(
    "publication_unavailable",
    parsed.success ? parsed.data.message : "The prepared publication could not be opened.",
    { cause: error },
  );
};
