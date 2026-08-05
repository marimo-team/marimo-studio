interface CellOutputChannel {
  channel: string;
}

const CELL_LOG_CHANNELS = new Set(["stderr", "stdout"]);

export const filterCellLogs = <Output extends CellOutputChannel>(
  outputs: Output[],
  showCellLogs: boolean,
): Output[] =>
  showCellLogs ? outputs : outputs.filter((output) => !CELL_LOG_CHANNELS.has(output.channel));
