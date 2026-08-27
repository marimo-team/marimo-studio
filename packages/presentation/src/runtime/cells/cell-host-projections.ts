import type { MarimoCellElement } from "../../cells/host";
import type { CellIndex } from "../../cells/index";
import type { RuntimeConfig } from "../../runtime-config/index";
import type { RuntimeCell } from "../runtime-cell";
import type { CellDiagnostic } from "./cell-projection";

import { projectionRequestForHost } from "../../projections/identity";
import { applyProjectionMetadata } from "../../projections/instances";
import {
  createProjectionResolutionContext,
  resolveHostProjection,
} from "../../projections/resolution";

const hostIds = new WeakMap<MarimoCellElement, number>();
let nextHostId = 0;

const getHostId = (host: MarimoCellElement): number => {
  const existing = hostIds.get(host);
  if (existing !== undefined) {
    return existing;
  }
  const created = nextHostId++;
  hostIds.set(host, created);
  return created;
};

export type CellHostProjection =
  | { key: number; kind: "duplicate"; host: MarimoCellElement }
  | {
      key: number;
      kind: "cell";
      projectionKey?: string;
      projectionPresent: boolean;
      cell: RuntimeCell | undefined;
      developer: boolean;
      diagnostic?: CellDiagnostic;
      host: MarimoCellElement;
      showCellLogs: boolean;
    };

export const projectCellHosts = (
  config: RuntimeConfig,
  cells: CellIndex<RuntimeCell>,
  hosts: readonly MarimoCellElement[],
): CellHostProjection[] => {
  const context = createProjectionResolutionContext(config, document);
  const resolved = hosts.map((host) => {
    const resolution = resolveHostProjection(
      config,
      host,
      projectionRequestForHost(host, "cell", host.cellName),
      context,
    );
    applyProjectionMetadata(host, resolution);
    return { host, resolution };
  });
  const primaryHosts = new Map<string, MarimoCellElement>();
  resolved.forEach(({ host, resolution }) => {
    if (resolution.ok && !primaryHosts.has(resolution.value.producer)) {
      primaryHosts.set(resolution.value.producer, host);
    }
  });
  const developer = config.dev || config.mode === "edit";

  return resolved.map(({ host, resolution }) => {
    const key = getHostId(host);
    if (resolution.ok && primaryHosts.get(resolution.value.producer) !== host) {
      return { key, kind: "duplicate", host };
    }
    const diagnostic = resolution.ok
      ? config.diagnostics.find(
          (item) =>
            item.projection === "cell" &&
            item.target === host.cellName &&
            (item.siteId === undefined || item.siteId === resolution.value.site.id),
        )
      : {
          code: resolution.error.code,
          message: resolution.error.message,
          hint: "Fix the projection target at its reported source site.",
        };
    const runtimeCellId = resolution.ok ? resolution.value.runtimeCellId : undefined;
    return {
      key,
      kind: "cell",
      projectionKey: resolution.ok
        ? `${resolution.value.producer}\0${runtimeCellId ?? ""}`
        : undefined,
      projectionPresent: resolution.ok,
      cell: runtimeCellId === undefined ? undefined : cells.byId.get(runtimeCellId),
      developer,
      diagnostic,
      host,
      showCellLogs: config.showCellLogs,
    };
  });
};
