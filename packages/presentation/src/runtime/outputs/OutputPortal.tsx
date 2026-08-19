import type {
  ProjectionDiagnostic,
  ValueBindingConfig,
} from "@marimo-studio/protocol/runtime-config";

import { createPortal } from "react-dom";

import type { MarimoOutputElement } from "../../outputs/host";
import type { OutputReader } from "../../outputs/reader";
import type { RuntimeConnectionState } from "../cell-state";
import type { RuntimeCell } from "../runtime-cell";

import { cellBindingKey } from "../../cells/bindings";
import { useDeliveryTimeout } from "../use-delivery-timeout";
import { valueCellFailure, valueCellModel } from "../values/value-cell-model";
import { ProjectedOutput } from "./ProjectedOutput";
import { useOutputHost } from "./use-output-host";
import { type OutputDiagnostic, useOutputProjection } from "./use-output-projection";

const structuralOutputFailure = (
  binding: ValueBindingConfig | undefined,
  diagnostic: ProjectionDiagnostic | undefined,
  modelFailure: "defining-cell-error" | "runtime-cell-not-received" | undefined,
  selector: string,
): OutputDiagnostic | undefined => {
  if (diagnostic) {
    return diagnostic;
  }
  if (!binding) {
    return {
      code: "unknown-selector",
      message: `Output ${JSON.stringify(selector)} is unavailable.`,
      hint: "Define the value or update this projection.",
    };
  }
  return modelFailure ? valueCellFailure(modelFailure, selector) : undefined;
};

export const OutputPortal = ({
  activeSelectors,
  binding,
  cell,
  connectionState,
  developer,
  diagnostic,
  host,
  readOutputs,
  revision,
  runtimeReady,
}: {
  activeSelectors: string[];
  binding: ValueBindingConfig | undefined;
  cell: RuntimeCell | undefined;
  connectionState: RuntimeConnectionState;
  developer: boolean;
  diagnostic?: ProjectionDiagnostic;
  host: MarimoOutputElement;
  readOutputs: OutputReader;
  revision: string;
  runtimeReady: boolean;
}) => {
  const selector = host.valueSelector;
  const deliveryTimedOut = useDeliveryTimeout(
    runtimeReady && binding !== undefined && cell === undefined && diagnostic === undefined,
    binding ? cellBindingKey(binding.cell) : undefined,
  );
  const model = valueCellModel(cell, runtimeReady, deliveryTimedOut);
  const sourceCellId = cell?.id;
  const bindingIdentity = binding
    ? `${binding.variable}\u0000${cellBindingKey(binding.cell)}`
    : undefined;
  const structuralFailure = structuralOutputFailure(binding, diagnostic, model.failure, selector);
  const projectionState = useOutputProjection({
    activeSelectors,
    bindingIdentity,
    blocked: structuralFailure !== undefined,
    connectionState,
    model,
    readOutputs,
    revision,
    selector,
    sourceCellId,
  });
  const effectiveFailure = structuralFailure ?? projectionState.failure;
  useOutputHost({
    bindingVariable: binding?.variable,
    failure: effectiveFailure,
    host,
    modelPhase: model.phase,
    pending: projectionState.pending,
    projection: projectionState.projection,
    projectionCurrent: projectionState.projectionCurrent,
    runtimeCellId: sourceCellId,
    selector,
  });

  if (effectiveFailure) {
    const message = developer ? effectiveFailure.message : "This section is unavailable.";
    return createPortal(
      <div className="marimo-cell-diagnostic" role="status">
        <strong>{message}</strong>
        {developer && effectiveFailure.hint ? <span>{effectiveFailure.hint}</span> : null}
      </div>,
      host,
    );
  }
  if (!projectionState.projection) {
    return null;
  }
  return createPortal(
    <ProjectedOutput
      output={projectionState.projection.output}
      stale={
        projectionState.pending || model.phase !== "ready" || !projectionState.projectionCurrent
      }
    />,
    host,
  );
};
