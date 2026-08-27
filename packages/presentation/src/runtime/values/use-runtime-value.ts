import type { ValueReadError } from "@marimo-studio/protocol/value-read";

import { useEffect, useLayoutEffect } from "react";

import type { RuntimeProjectionRequest as ProjectionRequest } from "../../projections/resolution";
import type { ValueReader } from "../../values/reader";
import type { RuntimeConnectionState } from "../cell-state";
import type { RuntimeCell } from "../runtime-cell";

import { errorMessage } from "../../errors";
import { getRuntimeConfig } from "../../runtime-config";
import { markValueError, markValuePending, setValueRuntimeCell } from "../../values/hosts";
import { ValueRequestError } from "../../values/remote";
import { applyValueReadResponse } from "../../values/response";
import { retryProjectionRefresh } from "../retry-projection-refresh";
import { useDeliveryTimeout } from "../use-delivery-timeout";
import { valueCellFailure, valueCellModel } from "./value-cell-model";

const requestFailure = (cause: unknown): ValueReadError => ({
  code: cause instanceof ValueRequestError ? cause.code : "value-request-failed",
  message: errorMessage(cause),
});

export const useRuntimeValue = ({
  projectionRevision,
  selectors,
  projections,
  cell,
  connectionState,
  runtimeReady,
  readValues,
}: {
  projectionRevision: string;
  selectors: string[];
  projections: ProjectionRequest[];
  cell: RuntimeCell | undefined;
  connectionState: RuntimeConnectionState;
  runtimeReady: boolean;
  readValues: ValueReader;
}): void => {
  const deliveryTimedOut = useDeliveryTimeout(runtimeReady && cell === undefined, cell?.id);
  const model = valueCellModel(cell, runtimeReady, deliveryTimedOut);

  useLayoutEffect(() => {
    setValueRuntimeCell(selectors, model.cellId, projectionRevision);
    return () => setValueRuntimeCell(selectors, null, projectionRevision);
  }, [model.cellId, projectionRevision, selectors]);

  useLayoutEffect(() => {
    if (model.phase === "loading" || model.phase === "stale") {
      selectors.forEach((selector) => markValuePending(selector, projectionRevision));
      return;
    }
    const failure = model.failure;
    if (model.phase === "error" && failure) {
      selectors.forEach((selector) =>
        markValueError(selector, valueCellFailure(failure, selector), projectionRevision),
      );
    }
  }, [model.failure, model.phase, projectionRevision, selectors]);

  useEffect(() => {
    if (connectionState !== "OPEN" || model.phase !== "ready") {
      return;
    }

    selectors.forEach((selector) => markValuePending(selector, projectionRevision));
    const controller = new AbortController();
    let current = true;
    void retryProjectionRefresh(controller.signal, () =>
      readValues({ revision: getRuntimeConfig().revision, projections }, controller.signal),
    )
      .then((response) => {
        if (!current) {
          return;
        }
        applyValueReadResponse(selectors, response, projectionRevision);
      })
      .catch((cause: unknown) => {
        if (!current || (cause instanceof DOMException && cause.name === "AbortError")) {
          return;
        }
        const failure = requestFailure(cause);
        selectors.forEach((selector) => markValueError(selector, failure, projectionRevision));
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [
    connectionState,
    model.cellId,
    model.phase,
    model.version,
    projections,
    projectionRevision,
    readValues,
    selectors,
  ]);
};
