import type { MarimoCellElement } from "../../cells/host";
import type { RuntimeConfig } from "../../runtime-config/index";
import type { RuntimeCell } from "../runtime-cell";
import type { CellDiagnostic } from "./cell-projection";

import { cellBindingKey, type CellIndex, resolveCellBinding } from "../../cells/bindings";

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
      bindingKey?: string;
      bindingPresent: boolean;
      cell: RuntimeCell | undefined;
      developer: boolean;
      diagnostic?: CellDiagnostic;
      host: MarimoCellElement;
    };

export const projectCellHosts = (
  config: RuntimeConfig,
  cells: CellIndex<RuntimeCell>,
  hosts: readonly MarimoCellElement[],
): CellHostProjection[] => {
  const diagnostics = new Map<string, CellDiagnostic>();
  config.diagnostics.forEach((diagnostic) => {
    if (diagnostic.projection === "cell") {
      diagnostics.set(diagnostic.target, diagnostic);
    }
  });
  const primaryHosts = new Map<string, MarimoCellElement>();
  hosts.forEach((host) => {
    if (!primaryHosts.has(host.cellName)) {
      primaryHosts.set(host.cellName, host);
    }
  });
  const developer = config.dev || config.mode === "edit";

  return hosts.map((host) => {
    const key = getHostId(host);
    if (primaryHosts.get(host.cellName) !== host) {
      return { key, kind: "duplicate", host };
    }
    const binding = config.cellBindings[host.cellName];
    return {
      key,
      kind: "cell",
      bindingKey: binding ? cellBindingKey(binding) : undefined,
      bindingPresent: binding !== undefined,
      cell: resolveCellBinding(binding, cells),
      developer,
      diagnostic: diagnostics.get(host.cellName),
      host,
    };
  });
};
