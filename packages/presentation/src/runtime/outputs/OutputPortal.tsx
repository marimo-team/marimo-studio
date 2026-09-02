import type { ProjectionDiagnostic } from "@marimo-studio/protocol/runtime-config";

import { createPortal } from "react-dom";

import type { MarimoOutputElement } from "../../outputs/host";
import type { OutputReader } from "../../outputs/reader";
import type {
  ProjectionResolutionFailure,
  ResolvedProjection,
  RuntimeProjectionRequest as ProjectionRequest,
} from "../../projections/resolution";
import type { RuntimeConnectionState } from "../cell-state";
import type { RuntimeCell } from "../runtime-cell";

import { useDeliveryTimeout } from "../use-delivery-timeout";
import { valueCellFailure, valueCellModel } from "../values/value-cell-model";
import { ProjectedOutput } from "./ProjectedOutput";
import { useOutputHost } from "./use-output-host";
import { type OutputDiagnostic, useOutputProjection } from "./use-output-projection";

const structuralOutputFailure = (
  projection: ResolvedProjection | undefined,
  resolutionFailure: ProjectionResolutionFailure | undefined,
  diagnostic: ProjectionDiagnostic | undefined,
  modelFailure: "defining-cell-error" | "runtime-cell-not-received" | undefined,
  selector: string,
): OutputDiagnostic | undefined => {
  if (diagnostic) {
    return diagnostic;
  }
  if (resolutionFailure) {
    return {
      code: resolutionFailure.code,
      message: resolutionFailure.message,
      hint: "Fix the projection target at its reported source site.",
    };
  }
  if (!projection) {
    return {
      code: "unknown-selector",
      message: `Output ${JSON.stringify(selector)} is unavailable.`,
      hint: "Define the value or update this projection.",
    };
  }
  return modelFailure ? valueCellFailure(modelFailure, selector) : undefined;
};

export const OutputPortal = ({
  activeProjections,
  projection,
  resolutionFailure,
  cell,
  connectionState,
  developer,
  diagnostic,
  host,
  readOutputs,
  runtimeReady,
}: {
  activeProjections: ProjectionRequest[];
  projection: ResolvedProjection | undefined;
  resolutionFailure: ProjectionResolutionFailure | undefined;
  cell: RuntimeCell | undefined;
  connectionState: RuntimeConnectionState;
  developer: boolean;
  diagnostic?: ProjectionDiagnostic;
  host: MarimoOutputElement;
  readOutputs: OutputReader;
  runtimeReady: boolean;
}) => {
  const selector = host.valueSelector;
  const deliveryTimedOut = useDeliveryTimeout(
    runtimeReady && projection !== undefined && cell === undefined && diagnostic === undefined,
    projection ? `${projection.producer}\u0000${projection.runtimeCellId ?? ""}` : undefined,
  );
  const model = valueCellModel(cell, runtimeReady, deliveryTimedOut);
  const sourceCellId = cell?.id;
  const projectionIdentity = projection
    ? `${projection.variable ?? ""}\u0000${projection.producer}`
    : undefined;
  const structuralFailure = structuralOutputFailure(
    projection,
    resolutionFailure,
    diagnostic,
    model.failure,
    selector,
  );
  const projectionState = useOutputProjection({
    activeProjections,
    request: projection?.request,
    projectionIdentity,
    blocked: structuralFailure !== undefined,
    connectionState,
    model,
    readOutputs,
    selector,
    sourceCellId,
  });
  const effectiveFailure = structuralFailure ?? projectionState.failure;
  useOutputHost({
    projectionVariable: projection?.variable ?? undefined,
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
