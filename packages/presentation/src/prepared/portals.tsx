import type { PreparedCellPresentationSnapshot } from "@marimo-studio/marimo-frontend/prepared-presentation";

import {
  PreparedCellPresentation,
  ProjectedOutputArea,
} from "@marimo-studio/marimo-frontend/prepared-presentation";
import { useLayoutEffect, useMemo, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

import type { MarimoCellElement } from "../cells/host.ts";
import type { MarimoOutputElement } from "../outputs/host.ts";
import type {
  PreparedCellSnapshot,
  PreparedOutputSnapshot,
  PreparedProjectionSnapshot,
} from "./records.ts";

import { getCellHosts, setCellHostState, subscribeCellHosts } from "../cells/host.ts";
import { getOutputHosts, setOutputHostState, subscribeOutputHosts } from "../outputs/host.ts";
import { setProjectionRuntimeCell } from "../projections/instances.ts";
import { createProjectionInventory } from "../projections/resolution.ts";
import { useRuntimeProjectionConfig } from "../runtime/use-runtime-config.ts";

const hostIds = new WeakMap<HTMLElement, number>();
let nextHostId = 0;

const hostId = (host: HTMLElement): number => {
  const current = hostIds.get(host);
  if (current !== undefined) {
    return current;
  }
  const created = nextHostId++;
  hostIds.set(host, created);
  return created;
};

const clearDiagnostics = (host: HTMLElement): void => {
  delete host.dataset.marimoDiagnosticCode;
  delete host.dataset.marimoDiagnosticMessage;
  delete host.dataset.marimoDiagnosticHint;
};

interface ProjectionFailure {
  readonly code: string;
  readonly message: string;
}

const FailedProjection = ({ failure }: { failure: ProjectionFailure }) => (
  <div className="marimo-cell-diagnostic" role="status">
    <strong>{failure.message}</strong>
  </div>
);

const showFailure = (host: HTMLElement, failure: ProjectionFailure): void => {
  delete host.dataset.marimoSelector;
  delete host.dataset.outputMime;
  setProjectionRuntimeCell(host, undefined);
  clearDiagnostics(host);
  host.dataset.marimoDiagnosticCode = failure.code;
  host.dataset.marimoDiagnosticMessage = failure.message;
};

const PreparedOutputPortal = ({
  host,
  rejection,
  snapshot,
  timestamp,
}: {
  host: MarimoOutputElement;
  rejection: ProjectionFailure | undefined;
  snapshot: PreparedOutputSnapshot | undefined;
  timestamp: number;
}) => {
  const name = host.valueSelector;
  const failure = useMemo<ProjectionFailure | undefined>(
    () =>
      rejection ??
      (snapshot === undefined
        ? {
            code: "prepared-output-missing",
            message: `Prepared output ${JSON.stringify(name)} is unavailable.`,
          }
        : undefined),
    [name, rejection, snapshot],
  );
  useLayoutEffect(() => {
    const selector = host.valueSelector;
    if (failure || snapshot === undefined) {
      if (failure) {
        showFailure(host, failure);
        setOutputHostState(host, "error", { selector, ...failure });
      }
      return;
    }
    clearDiagnostics(host);
    host.dataset.marimoSelector = selector;
    setProjectionRuntimeCell(host, snapshot.ownerCellId);
    const outputMime = snapshot.output?.mimetype;
    if (outputMime === undefined) {
      delete host.dataset.outputMime;
    } else {
      host.dataset.outputMime = outputMime;
    }
    setOutputHostState(host, "ready", {
      selector,
      cellId: snapshot.ownerCellId,
      mimetype: outputMime,
    });
  }, [failure, host, snapshot]);

  if (failure || snapshot === undefined) {
    return failure ? createPortal(<FailedProjection failure={failure} />, host) : null;
  }
  if (snapshot.output === null) {
    return null;
  }
  return createPortal(
    <ProjectedOutputArea
      accessibleName={host.getAttribute("aria-label")?.trim() || undefined}
      output={{
        ownerCellId: snapshot.ownerCellId,
        channel: snapshot.output.channel,
        mimetype: snapshot.output.mimetype,
        data: snapshot.output.data,
        timestamp,
        resetUiObjectIds: [],
      }}
      stale={false}
    />,
    host,
  );
};

const PreparedCellPortal = ({
  host,
  rejection,
  snapshot,
  timestamp,
}: {
  host: MarimoCellElement;
  rejection: ProjectionFailure | undefined;
  snapshot: PreparedCellSnapshot | undefined;
  timestamp: number;
}) => {
  const name = host.cellName;
  const failure = useMemo<ProjectionFailure | undefined>(
    () =>
      rejection ??
      (snapshot === undefined
        ? {
            code: "prepared-cell-missing",
            message: `Prepared cell ${JSON.stringify(name)} is unavailable.`,
          }
        : undefined),
    [name, rejection, snapshot],
  );
  useLayoutEffect(() => {
    const alias = host.cellName;
    if (failure || snapshot === undefined) {
      if (failure) {
        showFailure(host, failure);
        setCellHostState(host, "error", { alias, ...failure });
      }
      return;
    }
    clearDiagnostics(host);
    host.dataset.marimoSelector = alias;
    setProjectionRuntimeCell(host, snapshot.cell.id);
    const outputMime = snapshot.output?.mimetype;
    if (outputMime === undefined) {
      delete host.dataset.outputMime;
    } else {
      host.dataset.outputMime = outputMime;
    }
    setCellHostState(host, "ready", {
      alias,
      runtimeId: snapshot.cell.id,
      outputMime,
    });
  }, [failure, host, snapshot]);

  if (failure || snapshot === undefined) {
    return failure ? createPortal(<FailedProjection failure={failure} />, host) : null;
  }
  const prepared: PreparedCellPresentationSnapshot = {
    accessibleName: host.getAttribute("aria-label")?.trim() || host.cellName,
    cellId: snapshot.cell.id,
    cellName: snapshot.cell.name ?? "_",
    consoleOutputs: snapshot.console.map((output) => ({ ...output, timestamp })),
    output: snapshot.output === null ? null : { ...snapshot.output, timestamp },
  };
  return createPortal(<PreparedCellPresentation snapshot={prepared} />, host);
};

export const PreparedProjectionPortals = ({
  snapshot,
  timestamp,
}: {
  snapshot: PreparedProjectionSnapshot;
  timestamp: number;
}) => {
  const cellHosts = useSyncExternalStore(subscribeCellHosts, getCellHosts, getCellHosts);
  const outputHosts = useSyncExternalStore(subscribeOutputHosts, getOutputHosts, getOutputHosts);
  const projectionConfig = useRuntimeProjectionConfig();
  // Prepared delivery applies the same site policy as live outputs, so a
  // captured record reaches only hosts whose site permits its target.
  const rejections = useMemo(() => {
    const inventory = createProjectionInventory(projectionConfig, document);
    const rejected = new Map<HTMLElement, ProjectionFailure>();
    const check = (host: HTMLElement, kind: "cell" | "output") => {
      const { resolution } = inventory.resolve(host, kind);
      if (!resolution.ok) {
        rejected.set(host, { code: resolution.error.code, message: resolution.error.message });
      }
    };
    outputHosts.forEach((host) => check(host, "output"));
    cellHosts.forEach((host) => check(host, "cell"));
    return rejected;
  }, [cellHosts, outputHosts, projectionConfig]);
  const cells = useMemo(
    () => new Map(snapshot.cells.map((cell) => [cell.alias, cell])),
    [snapshot.cells],
  );
  const outputs = useMemo(
    () => new Map(snapshot.outputs.map((output) => [output.selector, output])),
    [snapshot.outputs],
  );

  return (
    <>
      {outputHosts.map((host) => (
        <PreparedOutputPortal
          key={`output:${hostId(host)}:${host.valueSelector}`}
          host={host}
          rejection={rejections.get(host)}
          snapshot={outputs.get(host.valueSelector)}
          timestamp={timestamp}
        />
      ))}
      {cellHosts.map((host) => (
        <PreparedCellPortal
          key={`cell:${hostId(host)}:${host.cellName}`}
          host={host}
          rejection={rejections.get(host)}
          snapshot={cells.get(host.cellName)}
          timestamp={timestamp}
        />
      ))}
    </>
  );
};
