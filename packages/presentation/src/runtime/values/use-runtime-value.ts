import type { ValueReadError } from "@marimo-studio/protocol/value-read";

import { useEffect, useLayoutEffect } from "react";

import type { ValueReader } from "../../values/reader";
import type { RuntimeConnectionState } from "../cell-state";
import type { RuntimeCell } from "../runtime-cell";

import { errorMessage } from "../../errors";
import { markValueError, markValuePending, setValueRuntimeCell } from "../../values/hosts";
import { ValueRequestError } from "../../values/remote";
import { applyValueReadResponse } from "../../values/response";
import { useDeliveryTimeout } from "../use-delivery-timeout";
import { valueCellFailure, valueCellModel } from "./value-cell-model";

const requestFailure = (cause: unknown): ValueReadError => ({
  code: cause instanceof ValueRequestError ? cause.code : "value-request-failed",
  message: errorMessage(cause),
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
  connectionState: RuntimeConnectionState;
  runtimeReady: boolean;
  readValues: ValueReader;
}): void => {
  const deliveryTimedOut = useDeliveryTimeout(runtimeReady && cell === undefined, cell?.id);
  const model = valueCellModel(cell, runtimeReady, deliveryTimedOut);

  useLayoutEffect(() => {
    setValueRuntimeCell(selectors, model.cellId);
    return () => setValueRuntimeCell(selectors, null);
  }, [model.cellId, selectors]);

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
  }, [model.failure, model.phase, selectors]);

  useEffect(() => {
    if (connectionState !== "OPEN" || model.phase !== "ready") {
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
      .catch((cause: unknown) => {
        if (!current || (cause instanceof DOMException && cause.name === "AbortError")) {
          return;
        }
        const failure = requestFailure(cause);
        selectors.forEach((selector) => markValueError(selector, failure));
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [connectionState, model.cellId, model.phase, model.version, readValues, revision, selectors]);
};
