import { useMemo, useSyncExternalStore } from "react";

import type { CellIndex } from "../../cells/index";
import type { OutputReader } from "../../outputs/reader";
import type { ProjectionHostBinding } from "../../projections/resolution";
import type { RuntimeConnectionState } from "../cell-state";
import type { RuntimeCell } from "../runtime-cell";

import { getOutputHosts, subscribeOutputHosts } from "../../outputs/host";
import { projectionRequestForHost } from "../../projections/identity";
import {
  createProjectionResolutionContext,
  resolveHostProjection,
} from "../../projections/resolution";
import { useRuntimeProjectionConfig } from "../use-runtime-config";
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
  const projectionConfig = useRuntimeProjectionConfig();
  const hosts = useSyncExternalStore(subscribeOutputHosts, getOutputHosts, getOutputHosts);
  const { resolvedHosts, primaryHosts, activeProjections } = useMemo(() => {
    const context = createProjectionResolutionContext(projectionConfig, document);
    const resolved = hosts.map((host) => {
      const resolution = resolveHostProjection(
        projectionConfig,
        host,
        projectionRequestForHost(host, "output", host.valueSelector),
        context,
      );
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
    readOutputs,
    projectionRevision: projectionConfig.projectionRevision,
    runtimeReady,
  });

  return resolvedHosts.map(({ binding, host }) => {
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
};
