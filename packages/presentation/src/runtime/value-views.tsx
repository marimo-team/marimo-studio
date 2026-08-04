import { outputIsStale } from "@marimo-studio/marimo-frontend/cells";
import { WebSocketState } from "@marimo-studio/marimo-frontend/runtime";
import { useEffect, useLayoutEffect, useMemo, useState, useSyncExternalStore } from "react";

import type { ValueReader } from "../values/reader";
import type { RuntimeCell } from "./runtime-cell";

import { cellBindingKey, type CellIndex, resolveCellBinding } from "../cells/bindings";
import { errorMessage } from "../errors";
import {
  type CellBindingConfig,
  getRuntimeConfig,
  subscribeRuntimeConfig,
  type ValueBindingConfig,
} from "../runtime-config/index";
import { applyValues, markValueError, markValuePending } from "../values/index";
import { ValueRequestError } from "../values/remote";
import { CELL_DELIVERY_TIMEOUT_MS } from "./cell-state";
import { valueCellPhase } from "./value-cell-state";

const RuntimeValueCell = ({
  selectors,
  cell,
  connectionState,
  runtimeReady,
  readValues,
}: {
  selectors: string[];
  cell: RuntimeCell | undefined;
  connectionState: WebSocketState;
  runtimeReady: boolean;
  readValues: ValueReader;
}) => {
  const cellId = cell?.id ?? null;
  const hasCell = cell !== undefined;
  const [deliveryTimedOut, setDeliveryTimedOut] = useState(false);
  useEffect(() => {
    setDeliveryTimedOut(false);
    if (!runtimeReady || hasCell) {
      return;
    }
    const timeout = setTimeout(() => setDeliveryTimedOut(true), CELL_DELIVERY_TIMEOUT_MS);
    return () => clearTimeout(timeout);
  }, [cellId, hasCell, runtimeReady]);

  const version = cell?.lastRunStartTimestamp ?? null;
  const status = cell?.status ?? "missing";
  const errored = cell?.errored ?? false;
  const stale = cell ? outputIsStale(cell, cell.edited) : false;
  const phase = valueCellPhase({
    runtimeReady,
    hasCell,
    disabled: cell?.config.disabled ?? false,
    status,
    version,
    errored,
    stale,
    deliveryTimedOut,
  });

  useLayoutEffect(() => {
    if (phase === "loading" || phase === "stale") {
      selectors.forEach(markValuePending);
      return;
    }
    if (phase === "error") {
      selectors.forEach((selector) => {
        markValueError(
          selector,
          !hasCell && deliveryTimedOut
            ? {
                code: "runtime-cell-not-received",
                message: `The cell backing ${JSON.stringify(selector)} did not reach the browser.`,
                hint: "Wait for the notebook to settle, then reload the view.",
              }
            : {
                code: "defining-cell-error",
                message: `The cell backing ${JSON.stringify(selector)} is unavailable.`,
              },
        );
      });
    }
  }, [deliveryTimedOut, hasCell, phase, selectors]);

  useEffect(() => {
    if (connectionState !== WebSocketState.OPEN || phase !== "ready") {
      return;
    }

    selectors.forEach(markValuePending);
    const controller = new AbortController();
    let current = true;
    void readValues(selectors, controller.signal)
      .then((response) => {
        if (!current) {
          return;
        }
        applyValues(response.values);
        selectors.forEach((selector) => {
          const error = response.errors[selector];
          if (error) {
            markValueError(selector, error);
            return;
          }
          if (!Object.hasOwn(response.values, selector)) {
            markValueError(selector, {
              code: "missing-value-response",
              message: `The kernel response omitted ${JSON.stringify(selector)}.`,
            });
          }
        });
      })
      .catch((error: unknown) => {
        if (!current || (error instanceof DOMException && error.name === "AbortError")) {
          return;
        }
        selectors.forEach((selector) => {
          markValueError(selector, {
            code: error instanceof ValueRequestError ? error.code : "value-request-failed",
            message: errorMessage(error),
          });
        });
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [cellId, connectionState, phase, readValues, selectors, version]);

  return null;
};

const RuntimeValues = ({
  bindings,
  cells,
  connectionState,
  runtimeReady,
  readValues,
}: {
  bindings: Record<string, ValueBindingConfig>;
  cells: CellIndex<RuntimeCell>;
  connectionState: WebSocketState;
  runtimeReady: boolean;
  readValues: ValueReader;
}) => {
  const groups = useMemo(() => {
    const byCell = new Map<string, { binding: CellBindingConfig; selectors: Set<string> }>();
    Object.entries(bindings).forEach(([selector, binding]) => {
      const key = cellBindingKey(binding.cell);
      const group = byCell.get(key) ?? {
        binding: binding.cell,
        selectors: new Set<string>(),
      };
      group.selectors.add(selector);
      byCell.set(key, group);
    });
    return Array.from(byCell, ([key, group]) => ({
      key,
      binding: group.binding,
      selectors: Array.from(group.selectors).sort(),
    }));
  }, [bindings]);

  return groups.map(({ key, binding, selectors }) => (
    <RuntimeValueCell
      key={key}
      selectors={selectors}
      cell={resolveCellBinding(binding, cells)}
      connectionState={connectionState}
      runtimeReady={runtimeReady}
      readValues={readValues}
    />
  ));
};

export const ConfiguredRuntimeValues = (
  props: Omit<Parameters<typeof RuntimeValues>[0], "bindings">,
) => {
  const config = useSyncExternalStore(subscribeRuntimeConfig, getRuntimeConfig, getRuntimeConfig);
  return <RuntimeValues {...props} bindings={config.valueBindings} />;
};
