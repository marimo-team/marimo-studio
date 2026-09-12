import type { RenderedOutput } from "@marimo-studio/protocol/output-read";

import { useCallback, useMemo, useState, useSyncExternalStore } from "react";

import type { CellIndex } from "../../cells/index";
import type { OutputReader } from "../../outputs/reader";
import type { ProjectionHostBinding } from "../../projections/resolution";
import type { RuntimeConnectionState } from "../cell-state";
import type { RuntimeCell } from "../runtime-cell";

import { getOutputHosts, subscribeOutputHosts } from "../../outputs/host";
import { createProjectionInventory } from "../../projections/resolution";
import { useRuntimeProjectionConfig } from "../use-runtime-config";
import { DuplicateOutputPortal } from "./DuplicateOutputPortal";
import { OutputPortal } from "./OutputPortal";
import { OverlayOutputs } from "./OverlayOutputs";
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
  const projectionConfig = useRuntimeProjectionConfig();
  const [overlays, setOverlays] = useState<RenderedOutput[]>([]);
  const observeOutputs = useCallback<OutputReader>(
    async (request, signal) => {
      const response = await readOutputs(request, signal);
      if (!signal?.aborted)
        setOverlays((previous) => {
          const current = new Map(previous.map((output) => [output.ownerCellId, output]));
          const next = Object.values(response.overlays ?? {}).map((output) => {
            const cached = current.get(output.ownerCellId);
            return cached?.timestamp === output.timestamp ? cached : output;
          });
          return next.length === previous.length &&
            next.every((output, index) => output === previous[index])
            ? previous
            : next;
        });
      return response;
    },
    [readOutputs],
  );
  const runtimeCells = [...cells.byId.values()];
  const refreshKey =
    projectionConfig.mode === "edit" &&
    projectionConfig.runtime.id === "server" &&
    runtimeCells.every((cell) => cell.status !== "running" && cell.status !== "queued")
      ? JSON.stringify(runtimeCells.map((cell) => [cell.id, cell.lastRunStartTimestamp]))
      : undefined;
  const hosts = useSyncExternalStore(subscribeOutputHosts, getOutputHosts, getOutputHosts);
  const { resolvedHosts, primaryHosts, activeProjections } = useMemo(() => {
    const inventory = createProjectionInventory(projectionConfig, document);
    const resolved = hosts.map((host) => {
      const { resolution } = inventory.resolve(host, "output");
      const binding: ProjectionHostBinding = {
        resolution,
        projectionRevision: projectionConfig.projectionRevision,
      };
      return { binding, host };
    });
    const primary = new Map<string, (typeof hosts)[number]>();
    resolved.forEach(({ binding, host }) => {
      const { resolution } = binding;
      if (resolution.ok && !primary.has(resolution.value.request.target)) {
        primary.set(resolution.value.request.target, host);
      }
    });
    const active = resolved.flatMap(({ binding, host }) => {
      const { resolution } = binding;
      if (!resolution.ok || primary.get(resolution.value.request.target) !== host) {
        return [];
      }
      const runtimeId = resolution.value.runtimeCellId;
      const cell = runtimeId === undefined ? undefined : cells.byId.get(runtimeId);
      return canOwnOutput(cell) ? [resolution.value.request] : [];
    });
    return {
      resolvedHosts: resolved,
      primaryHosts: primary,
      activeProjections: active,
    };
  }, [cells, hosts, projectionConfig]);
  const ownedOutputReader = useOutputLifecycle({
    activeProjections,
    connectionState,
    readOutputs: observeOutputs,
    projectionRevision: projectionConfig.projectionRevision,
    runtimeReady,
    refreshKey,
  });

  const projections = resolvedHosts.map(({ binding, host }) => {
    const { resolution } = binding;
    if (resolution.ok && primaryHosts.get(resolution.value.request.target) !== host) {
      return <DuplicateOutputPortal binding={binding} key={hostId(host)} host={host} />;
    }
    const diagnostic = projectionConfig.diagnostics.find(
      (item) =>
        item.projection === "output" &&
        item.target === host.valueSelector &&
        (item.siteId === undefined ||
          item.siteId === (resolution.ok ? resolution.value.site.id : undefined)),
    );
    const projection = resolution.ok ? resolution.value : undefined;
    const runtimeId = projection?.runtimeCellId;
    return (
      <OutputPortal
        key={hostId(host)}
        activeProjections={activeProjections}
        binding={binding}
        cell={runtimeId === undefined ? undefined : cells.byId.get(runtimeId)}
        connectionState={connectionState}
        developer={projectionConfig.dev || projectionConfig.mode === "edit"}
        diagnostic={diagnostic}
        host={host}
        readOutputs={ownedOutputReader}
        runtimeReady={runtimeReady}
      />
    );
  });
  return (
    <>
      {projections}
      <OverlayOutputs outputs={overlays} />
    </>
  );
};
