import type { ValueReadError } from "@marimo-studio/protocol/value-read";

import { WebSocketState } from "@marimo-studio/marimo-frontend/runtime";
import { useEffect, useLayoutEffect, useMemo } from "react";

import type { ValueReader } from "../../values/reader";
import type { RuntimeCell } from "../runtime-cell";

import { errorMessage } from "../../errors";
import { markValueError, markValuePending } from "../../values/hosts";
import { ValueRequestError } from "../../values/remote";
import { applyValueReadResponse } from "../../values/response";
import { useDeliveryTimeout } from "../use-delivery-timeout";
import { valueCellFailure, valueCellModel } from "./value-cell-model";

const requestFailure = (error: unknown): ValueReadError => ({
  code: error instanceof ValueRequestError ? error.code : "value-request-failed",
  message: errorMessage(error),
});

export const useRuntimeValue = ({
  revision,
  selectors,
  cell,
  connectionState,
  runtimeReady,
  readValues,
}: {
  revision: string;
  selectors: string[];
  cell: RuntimeCell | undefined;
  connectionState: WebSocketState;
  runtimeReady: boolean;
  readValues: ValueReader;
}): void => {
  const deliveryTimedOut = useDeliveryTimeout(runtimeReady && cell === undefined, cell?.id);
  const model = useMemo(
    () => valueCellModel(cell, runtimeReady, deliveryTimedOut),
    [cell, deliveryTimedOut, runtimeReady],
  );

  useLayoutEffect(() => {
    if (model.phase === "loading" || model.phase === "stale") {
      selectors.forEach(markValuePending);
      return;
    }
    const failure = model.failure;
    if (model.phase === "error" && failure) {
      selectors.forEach((selector) =>
        markValueError(selector, valueCellFailure(failure, selector)),
      );
    }
  }, [model, selectors]);

  useEffect(() => {
    if (connectionState !== WebSocketState.OPEN || model.phase !== "ready") {
      return;
    }

    selectors.forEach(markValuePending);
    const controller = new AbortController();
    let current = true;
    void readValues({ revision, selectors }, controller.signal)
      .then((response) => {
        if (!current) {
          return;
        }
        applyValueReadResponse(selectors, response);
      })
      .catch((error: unknown) => {
        if (!current || (error instanceof DOMException && error.name === "AbortError")) {
          return;
        }
        const failure = requestFailure(error);
        selectors.forEach((selector) => markValueError(selector, failure));
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [connectionState, model.cellId, model.phase, model.version, readValues, revision, selectors]);
};
