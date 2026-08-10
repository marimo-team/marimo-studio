import { useLayoutEffect } from "react";

import type { MarimoOutputElement } from "../../outputs/host";
import type { ValueCellModel } from "../values/value-cell-model";
import type { OutputDiagnostic, OutputProjection } from "./use-output-projection";

import { setOutputHostState } from "../../outputs/host";

const setDataset = (host: HTMLElement, name: string, value: string | undefined) => {
  if (value) {
    host.dataset[name] = value;
  } else {
    delete host.dataset[name];
  }
};

export const useOutputHost = ({
  bindingVariable,
  failure,
  host,
  modelPhase,
  pending,
  projection,
  projectionCurrent,
  selector,
}: {
  bindingVariable: string | undefined;
  failure: OutputDiagnostic | undefined;
  host: MarimoOutputElement;
  modelPhase: ValueCellModel["phase"];
  pending: boolean;
  projection: OutputProjection | undefined;
  projectionCurrent: boolean;
  selector: string;
}): void => {
  const cellId = projection?.cellId;
  const mimetype = projection?.output.mimetype;
  const failureCode = failure?.code;
  const failureMessage = failure?.message;
  const failureHint = failure?.hint;
  const hasFailure = failure !== undefined;
  const hasProjection = projection !== undefined;

  useLayoutEffect(() => {
    setDataset(host, "marimoSelector", selector);
    setDataset(host, "marimoVariable", bindingVariable);
    setDataset(host, "runtimeCellId", cellId);
    setDataset(host, "outputMime", mimetype);
    setDataset(host, "marimoDiagnosticCode", failureCode);
    setDataset(host, "marimoDiagnosticMessage", failureMessage);
    setDataset(host, "marimoDiagnosticHint", failureHint);
    const detail = {
      selector,
      cellId,
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
  }, [
    bindingVariable,
    cellId,
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
    selector,
  ]);
};
