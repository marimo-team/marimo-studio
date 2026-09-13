import { useLayoutEffect } from "react";

import type { MarimoOutputElement } from "../../outputs/host";
import type { ProjectionHostBinding } from "../../projections/resolution";
import type { ValueCellModel } from "../values/value-cell-model";
import type { OutputDiagnostic, OutputProjection } from "./use-output-projection";

import { setOutputHostState } from "../../outputs/host";
import {
  applyProjectionMetadata,
  resetProjectionHostMetadata,
  setProjectionRuntimeCell,
} from "../../projections/instances.ts";

const setDataset = (host: HTMLElement, name: string, value: string | undefined) => {
  if (value) {
    host.dataset[name] = value;
  } else {
    delete host.dataset[name];
  }
};

export const useOutputHost = ({
  binding,
  projectionVariable,
  failure,
  host,
  modelPhase,
  pending,
  projection,
  projectionCurrent,
  runtimeCellId,
  selector,
}: {
  binding: ProjectionHostBinding;
  projectionVariable: string | undefined;
  failure: OutputDiagnostic | undefined;
  host: MarimoOutputElement;
  modelPhase: ValueCellModel["phase"];
  pending: boolean;
  projection: OutputProjection | undefined;
  projectionCurrent: boolean;
  runtimeCellId: string | undefined;
  selector: string;
}): void => {
  const mimetype = projection?.output.mimetype;
  const failureCode = failure?.code;
  const failureMessage = failure?.message;
  const failureHint = failure?.hint;
  const hasFailure = failure !== undefined;
  const hasProjection = projection !== undefined;

  useLayoutEffect(() => {
    applyProjectionMetadata(host, binding.resolution, binding.projectionRevision);
    setDataset(host, "marimoSelector", selector);
    setDataset(host, "marimoVariable", projectionVariable);
    setProjectionRuntimeCell(host, runtimeCellId);
    setDataset(host, "outputMime", mimetype);
    setDataset(host, "marimoDiagnosticCode", failureCode);
    setDataset(host, "marimoDiagnosticMessage", failureMessage);
    setDataset(host, "marimoDiagnosticHint", failureHint);
    const detail = {
      selector,
      cellId: runtimeCellId,
      mimetype,
      code: failureCode,
      message: failureMessage,
      hint: failureHint,
    };
    if (hasFailure) {
      setOutputHostState(host, "error", detail);
    } else if (
      modelPhase === "loading" ||
      modelPhase === "stale" ||
      pending ||
      (hasProjection && !projectionCurrent)
    ) {
      setOutputHostState(host, hasProjection ? "stale" : "loading", detail);
    } else if (hasProjection && projectionCurrent) {
      setOutputHostState(host, "ready", detail);
    } else {
      setOutputHostState(host, "loading", detail);
    }
    return () => resetProjectionHostMetadata(host);
  }, [
    binding,
    projectionVariable,
    failureCode,
    failureHint,
    failureMessage,
    hasFailure,
    hasProjection,
    host,
    mimetype,
    modelPhase,
    pending,
    projectionCurrent,
    runtimeCellId,
    selector,
  ]);
};
