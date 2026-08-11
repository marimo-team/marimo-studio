import { useMemo, useSyncExternalStore } from "react";

import type { CellIndex } from "../../cells/bindings";
import type { OutputReader } from "../../outputs/reader";
import type { RuntimeConnectionState } from "../cell-state";
import type { RuntimeCell } from "../runtime-cell";

import { resolveCellBinding } from "../../cells/bindings";
import { getOutputHosts, subscribeOutputHosts } from "../../outputs/host";
import { useRuntimeConfig } from "../use-runtime-config";
import { DuplicateOutputPortal } from "./DuplicateOutputPortal";
import { OutputPortal } from "./OutputPortal";
import { useOutputLifecycle } from "./use-output-lifecycle";

const hostIds = new WeakMap<HTMLElement, number>();
let nextHostId = 0;

const hostId = (host: HTMLElement): number => {
  const existing = hostIds.get(host);
  if (existing !== undefined) {
    return existing;
  }
  const created = nextHostId++;
  hostIds.set(host, created);
  return created;
};

const canOwnOutput = (cell: RuntimeCell | undefined): boolean =>
  cell !== undefined &&
  !cell.config.disabled &&
  cell.status !== "disabled-transitively" &&
  !cell.errored;

export const RuntimeOutputs = ({
  cells,
  connectionState,
  readOutputs,
  runtimeReady,
}: {
  cells: CellIndex<RuntimeCell>;
  connectionState: RuntimeConnectionState;
  readOutputs: OutputReader;
  runtimeReady: boolean;
}) => {
  const config = useRuntimeConfig();
  const hosts = useSyncExternalStore(subscribeOutputHosts, getOutputHosts, getOutputHosts);
  const activeKey = Array.from(
    new Set(
      hosts
        .map((host) => host.valueSelector)
        .filter((selector) => {
          const binding = config.outputBindings[selector];
          return binding !== undefined && canOwnOutput(resolveCellBinding(binding.cell, cells));
        }),
    ),
  )
    .sort()
    .join("\u0000");
  const activeSelectors = useMemo(() => (activeKey ? activeKey.split("\u0000") : []), [activeKey]);
  useOutputLifecycle({
    activeSelectors,
    connectionState,
    readOutputs,
    revision: config.revision,
    runtimeReady,
  });

  const primaryHosts = new Map<string, (typeof hosts)[number]>();
  hosts.forEach((host) => {
    if (!primaryHosts.has(host.valueSelector)) {
      primaryHosts.set(host.valueSelector, host);
    }
  });

  return hosts.map((host) => {
    if (primaryHosts.get(host.valueSelector) !== host) {
      return <DuplicateOutputPortal key={`${hostId(host)}:${host.valueSelector}`} host={host} />;
    }
    const binding = config.outputBindings[host.valueSelector];
    const diagnostic = config.diagnostics.find(
      (item) => item.projection === "output" && item.target === host.valueSelector,
    );
    return (
      <OutputPortal
        key={`${hostId(host)}:${host.valueSelector}`}
        activeSelectors={activeSelectors}
        binding={binding}
        cell={resolveCellBinding(binding?.cell, cells)}
        connectionState={connectionState}
        developer={config.dev || config.mode === "edit"}
        diagnostic={diagnostic}
        host={host}
        readOutputs={readOutputs}
        revision={config.revision}
        runtimeReady={runtimeReady}
      />
    );
  });
};
