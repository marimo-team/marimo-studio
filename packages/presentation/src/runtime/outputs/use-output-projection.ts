import type { RenderedOutput } from "@marimo-studio/protocol/output-read";
import type { ValueReadError } from "@marimo-studio/protocol/value-read";

import { useEffect, useState } from "react";

import type { OutputReader } from "../../outputs/reader";
import type { RuntimeProjectionRequest as ProjectionRequest } from "../../projections/resolution";
import type { RuntimeConnectionState } from "../cell-state";
import type { ValueCellModel } from "../values/value-cell-model";

import { errorMessage } from "../../errors";
import { OutputRequestError } from "../../outputs/remote";
import { ownRecordValue } from "../../records";
import { getRuntimeConfig } from "../../runtime-config";
import { retryProjectionRefresh } from "../retry-projection-refresh";
import { useLatest } from "../use-latest";

export interface OutputDiagnostic {
  code: string;
  message: string;
  hint?: string;
}

export interface OutputProjection {
  output: RenderedOutput;
  sourceVersion: number | null;
}

interface OutputRequestState {
  failure?: OutputDiagnostic;
  identity: string;
  pending: boolean;
  projection?: OutputProjection;
}

export interface OutputProjectionState {
  failure?: OutputDiagnostic;
  pending: boolean;
  projection?: OutputProjection;
  projectionCurrent: boolean;
}

const requestFailure = (cause: unknown): ValueReadError => ({
  code: cause instanceof OutputRequestError ? cause.code : "output-request-failed",
  message: errorMessage(cause),
});

export const useOutputProjection = ({
  activeProjections,
  request,
  projectionIdentity,
  blocked,
  connectionState,
  model,
  readOutputs,
  selector,
  sourceCellId,
}: {
  activeProjections: ProjectionRequest[];
  request: ProjectionRequest | undefined;
  projectionIdentity: string | undefined;
  blocked: boolean;
  connectionState: RuntimeConnectionState;
  model: ValueCellModel;
  readOutputs: OutputReader;
  selector: string;
  sourceCellId: string | undefined;
}): OutputProjectionState => {
  const [state, setState] = useState<OutputRequestState>();
  const activeProjectionsRef = useLatest(activeProjections);
  const requestRef = useLatest(request);
  const requestIdentity =
    projectionIdentity && sourceCellId && request
      ? JSON.stringify([
          request.kind,
          request.siteId,
          request.instanceId,
          request.target,
          selector,
          projectionIdentity,
          sourceCellId,
        ])
      : undefined;

  useEffect(() => {
    const currentRequest = requestRef.current;
    if (
      !requestIdentity ||
      !currentRequest ||
      !sourceCellId ||
      blocked ||
      connectionState !== "OPEN" ||
      model.phase !== "ready"
    ) {
      return;
    }
    const controller = new AbortController();
    let current = true;
    const sourceVersion = model.version;
    setState((previous) => ({
      identity: requestIdentity,
      pending: true,
      projection: previous?.identity === requestIdentity ? previous.projection : undefined,
    }));

    const release = () => {
      void readOutputs({
        revision: getRuntimeConfig().revision,
        projections: [],
        activeProjections: activeProjectionsRef.current.filter(
          (active) =>
            active.siteId !== currentRequest.siteId ||
            active.instanceId !== currentRequest.instanceId,
        ),
      }).catch(() => {});
    };

    void retryProjectionRefresh(controller.signal, () =>
      readOutputs(
        {
          revision: getRuntimeConfig().revision,
          projections: [currentRequest],
          activeProjections: activeProjectionsRef.current,
        },
        controller.signal,
      ),
    )
      .then((response) => {
        if (!current) {
          return;
        }
        const failure =
          ownRecordValue(response.errors, selector) ?? ownRecordValue(response.errors, "*");
        const rendered = ownRecordValue(response.outputs, selector);
        if (failure) {
          setState({ failure, identity: requestIdentity, pending: false });
          release();
          return;
        }
        if (!rendered) {
          setState({
            failure: {
              code: "invalid-output-response",
              message: `The kernel returned no output for ${JSON.stringify(selector)}.`,
            },
            identity: requestIdentity,
            pending: false,
          });
          release();
          return;
        }
        setState({
          identity: requestIdentity,
          pending: false,
          projection: { output: rendered, sourceVersion },
        });
      })
      .catch((cause: unknown) => {
        if (!current || (cause instanceof DOMException && cause.name === "AbortError")) {
          return;
        }
        setState({
          failure: requestFailure(cause),
          identity: requestIdentity,
          pending: false,
        });
        release();
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [
    activeProjectionsRef,
    blocked,
    connectionState,
    model.phase,
    model.version,
    readOutputs,
    requestIdentity,
    requestRef,
    selector,
    sourceCellId,
  ]);

  const currentState = !blocked && state?.identity === requestIdentity ? state : undefined;
  const projectionCurrent = currentState?.projection?.sourceVersion === model.version;
  return {
    failure: currentState?.failure,
    pending: currentState?.pending ?? false,
    projection: currentState?.projection,
    projectionCurrent,
  };
};
