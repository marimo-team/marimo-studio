import {
  cellDomProps,
  ConsoleOutput,
  type flattenTopLevelNotebookCells,
  OutputArea,
  outputIsLoading,
  outputIsStale,
} from "./upstream/cells.ts";

type UpstreamCell = ReturnType<typeof flattenTopLevelNotebookCells>[number];

export type CellId = UpstreamCell["id"];
export type CellOutput = NonNullable<UpstreamCell["output"]>;
export type RuntimeCell = UpstreamCell;

export const cellOutputIsLoading = (status: RuntimeCell["status"]): boolean =>
  outputIsLoading(status);

export const cellOutputIsStale = (cell: RuntimeCell, edited: boolean): boolean =>
  outputIsStale(cell, edited);

export const CellPresentation = ({
  cell,
  consoleOutputs,
  loading,
  stale,
  onSubmitStdin,
}: {
  cell: RuntimeCell;
  consoleOutputs: CellOutput[];
  loading: boolean;
  stale: boolean;
  onSubmitStdin: (text: string, outputIndex: number) => void;
}) => (
  <div className="marimo" data-marimo-cell-output="" {...cellDomProps(cell.id, cell.name)}>
    <ConsoleOutput
      cellId={cell.id}
      cellName="_"
      consoleOutputs={consoleOutputs}
      stale={(cell.status === "queued" || cell.edited || cell.staleInputs) && !cell.interrupted}
      interrupted={cell.interrupted}
      debuggerActive={cell.debuggerActive}
      onSubmitDebugger={onSubmitStdin}
    />
    <OutputArea
      allowExpand={false}
      output={cell.output}
      cellId={cell.id}
      stale={stale}
      loading={loading}
    />
  </div>
);
