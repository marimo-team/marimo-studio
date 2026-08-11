import {
  cellDomProps,
  ConsoleOutput,
  type flattenTopLevelNotebookCells,
  OutputArea,
  outputIsLoading,
  outputIsStale,
} from "./upstream/cells.ts";

type UpstreamCell = ReturnType<typeof flattenTopLevelNotebookCells>[number];

export type CellId = string;

export interface CellOutput {
  channel: string;
  data: unknown;
  mimetype: string;
  timestamp: number;
}

export interface RuntimeCell {
  id: CellId;
  name: string;
  config: { disabled?: boolean };
  consoleOutputs: CellOutput[];
  debuggerActive: boolean;
  edited: boolean;
  errored: boolean;
  interrupted: boolean;
  lastRunStartTimestamp: number | null;
  output: CellOutput | null;
  staleInputs: boolean;
  status: string;
}

export const cellOutputIsLoading = (status: string): boolean =>
  outputIsLoading(status as Parameters<typeof outputIsLoading>[0]);

export const cellOutputIsStale = (cell: RuntimeCell, edited: boolean): boolean =>
  outputIsStale(cell as UpstreamCell, edited);

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
  <div
    className="marimo"
    data-marimo-cell-output=""
    {...cellDomProps(cell.id as UpstreamCell["id"], cell.name)}
  >
    <ConsoleOutput
      cellId={cell.id as UpstreamCell["id"]}
      cellName="_"
      consoleOutputs={consoleOutputs as UpstreamCell["consoleOutputs"]}
      stale={(cell.status === "queued" || cell.edited || cell.staleInputs) && !cell.interrupted}
      interrupted={cell.interrupted}
      debuggerActive={cell.debuggerActive}
      onSubmitDebugger={onSubmitStdin}
    />
    <OutputArea
      allowExpand={false}
      output={cell.output as UpstreamCell["output"]}
      cellId={cell.id as UpstreamCell["id"]}
      stale={stale}
      loading={loading}
    />
  </div>
);
