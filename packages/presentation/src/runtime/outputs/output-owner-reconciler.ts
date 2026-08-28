import type { OutputReadRequest, OutputReadResponse } from "@marimo-studio/protocol/output-read";

import type { OutputReader } from "../../outputs/reader";

import { OutputRequestError } from "../../outputs/remote";
import { ProjectionOwnerReconciler } from "../projection-owner-reconciler";

export class OutputOwnerReconciler extends ProjectionOwnerReconciler<
  OutputReadRequest,
  OutputReadResponse
> {
  constructor(source: OutputReader, retryDelay = 1_000) {
    super(source, retryDelay, (error) => error instanceof OutputRequestError && error.transient);
  }
}
