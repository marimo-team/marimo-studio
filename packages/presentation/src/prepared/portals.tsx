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

const MissingProjection = ({ kind, name }: { kind: "cell" | "output"; name: string }) => (
  <div className="marimo-cell-diagnostic" role="status">
    <strong>{`Prepared ${kind} ${JSON.stringify(name)} is unavailable.`}</strong>
  </div>
);

const PreparedOutputPortal = ({
  host,
  snapshot,
  timestamp,
}: {
  host: MarimoOutputElement;
  snapshot: PreparedOutputSnapshot | undefined;
  timestamp: number;
}) => {
  useLayoutEffect(() => {
    const selector = host.valueSelector;
    if (snapshot === undefined) {
      host.dataset.marimoDiagnosticCode = "prepared-output-missing";
      host.dataset.marimoDiagnosticMessage = `Prepared output ${JSON.stringify(selector)} is unavailable.`;
      setOutputHostState(host, "error", {
        selector,
        code: "prepared-output-missing",
        message: host.dataset.marimoDiagnosticMessage,
      });
      return;
    }
    clearDiagnostics(host);
    host.dataset.marimoSelector = selector;
    host.dataset.runtimeCellId = snapshot.ownerCellId;
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
  }, [host, snapshot]);

  if (snapshot === undefined) {
    return createPortal(<MissingProjection kind="output" name={host.valueSelector} />, host);
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
  snapshot,
  timestamp,
}: {
  host: MarimoCellElement;
  snapshot: PreparedCellSnapshot | undefined;
  timestamp: number;
}) => {
  useLayoutEffect(() => {
    const alias = host.cellName;
    if (snapshot === undefined) {
      host.dataset.marimoDiagnosticCode = "prepared-cell-missing";
      host.dataset.marimoDiagnosticMessage = `Prepared cell ${JSON.stringify(alias)} is unavailable.`;
      setCellHostState(host, "error", {
        alias,
        code: "prepared-cell-missing",
        message: host.dataset.marimoDiagnosticMessage,
      });
      return;
    }
    clearDiagnostics(host);
    host.dataset.marimoSelector = alias;
    host.dataset.runtimeCellId = snapshot.cell.id;
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
  }, [host, snapshot]);

  if (snapshot === undefined) {
    return createPortal(<MissingProjection kind="cell" name={host.cellName} />, host);
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
          snapshot={outputs.get(host.valueSelector)}
          timestamp={timestamp}
        />
      ))}
      {cellHosts.map((host) => (
        <PreparedCellPortal
          key={`cell:${hostId(host)}:${host.cellName}`}
          host={host}
          snapshot={cells.get(host.cellName)}
          timestamp={timestamp}
        />
      ))}
    </>
  );
};
