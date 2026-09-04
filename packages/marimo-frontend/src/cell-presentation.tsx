import { useState } from "react";

import type { flattenTopLevelNotebookCells } from "./upstream/cells.ts";

import {
  cellDomProps,
  OutputArea,
  OutputRenderer,
  outputIsLoading,
  outputIsStale,
} from "./upstream/prepared-cells.ts";

type UpstreamCell = ReturnType<typeof flattenTopLevelNotebookCells>[number];

export type CellId = UpstreamCell["id"];
export type CellOutput = NonNullable<UpstreamCell["output"]>;
export type CellConsoleOutput = UpstreamCell["consoleOutputs"][number];
export type RuntimeCell = UpstreamCell;

export const cellOutputIsLoading = (status: RuntimeCell["status"]): boolean =>
  outputIsLoading(status);

export const cellOutputIsStale = (cell: RuntimeCell, edited: boolean): boolean =>
  outputIsStale(cell, edited);

interface ProjectedCellPresentationProps {
  accessibleName?: string;
  cellId: CellId;
  cellName: string;
  consoleOutputs: CellConsoleOutput[];
  interrupted: boolean;
  loading: boolean;
  output: CellOutput | null;
  stale: boolean;
  onSubmitStdin: (text: string, outputIndex: number) => void;
}

export const ProjectedCellPresentation = ({
  accessibleName,
  cellId,
  cellName,
  consoleOutputs,
  interrupted,
  loading,
  output,
  stale,
  onSubmitStdin,
}: ProjectedCellPresentationProps) => {
  const [stdinValue, setStdinValue] = useState("");
  const pendingStdin = consoleOutputs.findLastIndex(
    (consoleOutput) => consoleOutput.channel === "stdin" && consoleOutput.response == null,
  );

  return (
    <div
      aria-label={accessibleName ?? cellName}
      className="marimo"
      data-marimo-cell-output=""
      data-marimo-presentation="projected-cell"
      role="group"
      {...cellDomProps(cellId, cellName)}
    >
      {consoleOutputs.length > 0 ? (
        <div className="console-output-area" data-testid="console-output-area">
          {consoleOutputs.map((consoleOutput, outputIndex) => {
            if (consoleOutput.channel === "pdb") {
              return null;
            }
            if (consoleOutput.channel !== "stdin") {
              return <OutputRenderer key={outputIndex} cellId={cellId} message={consoleOutput} />;
            }
            const password = consoleOutput.mimetype === "text/password";
            const hasResponse = consoleOutput.response != null && consoleOutput.response !== "";
            const wasInterrupted = interrupted && !hasResponse;
            return (
              <div className="marimo-projected-stdin" key={outputIndex}>
                <OutputRenderer cellId={cellId} message={consoleOutput} />
                {outputIndex === pendingStdin ? (
                  <input
                    aria-label={`${accessibleName ?? cellName} input`}
                    autoComplete="off"
                    autoFocus={true}
                    className="marimo-projected-stdin-input"
                    data-stdin-blocking={true}
                    data-testid="console-input"
                    type={password ? "password" : "text"}
                    value={stdinValue}
                    onChange={(event) => setStdinValue(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter" || event.shiftKey) {
                        return;
                      }
                      onSubmitStdin(stdinValue, outputIndex);
                      setStdinValue("");
                      event.preventDefault();
                      event.stopPropagation();
                    }}
                  />
                ) : null}
                {outputIndex !== pendingStdin && !password && !wasInterrupted ? (
                  <span aria-label="stdin response" className="marimo-projected-stdin-response">
                    {hasResponse ? consoleOutput.response : "(empty)"}
                  </span>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}
      <OutputArea
        allowExpand={false}
        output={output}
        cellId={cellId}
        stale={stale}
        loading={loading}
      />
    </div>
  );
};

export const CellPresentation = ({
  accessibleName,
  cell,
  consoleOutputs,
  loading,
  stale,
  onSubmitStdin,
}: {
  accessibleName?: string;
  cell: RuntimeCell;
  consoleOutputs: CellConsoleOutput[];
  loading: boolean;
  stale: boolean;
  onSubmitStdin: (text: string, outputIndex: number) => void;
}) => (
  <ProjectedCellPresentation
    accessibleName={accessibleName}
    cellId={cell.id}
    cellName={cell.name}
    consoleOutputs={consoleOutputs}
    interrupted={cell.interrupted}
    loading={loading}
    output={cell.output}
    stale={stale}
    onSubmitStdin={onSubmitStdin}
  />
);
