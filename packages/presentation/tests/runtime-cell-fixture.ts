import type { RuntimeCell } from "../src/runtime/runtime-cell.ts";

type RuntimeCellFixtureOptions = Partial<Omit<RuntimeCell, "id" | "lastRunStartTimestamp">> & {
  id?: string;
  lastRunStartTimestamp?: number | null;
};

const cellId = (value: string): RuntimeCell["id"] => {
  // SAFETY: RuntimeCell IDs carry a compile-time brand with no runtime parser.
  // Every fixture ID is a nonempty stable identifier controlled by the test.
  return value as RuntimeCell["id"];
};

const seconds = (value: number | null): RuntimeCell["lastRunStartTimestamp"] => {
  // SAFETY: The fixture timestamps represent seconds, which is the branded unit
  // required by lastRunStartTimestamp.
  return value as RuntimeCell["lastRunStartTimestamp"];
};

export const runtimeCellFixture = (overrides: RuntimeCellFixtureOptions = {}): RuntimeCell => {
  const { id = "cell-id", lastRunStartTimestamp = null, ...fields } = overrides;
  const base: RuntimeCell = {
    id: cellId(id),
    name: "_",
    code: "value = 1",
    edited: false,
    lastCodeRun: "value = 1",
    lastExecutionTime: null,
    config: { hide_code: false, disabled: false, column: null },
    serializedEditorState: null,
    output: null,
    outline: null,
    consoleOutputs: [],
    status: "idle",
    staleInputs: false,
    interrupted: false,
    stopped: false,
    errored: false,
    runStartTimestamp: null,
    runElapsedTimeMs: null,
    lastRunStartTimestamp: seconds(lastRunStartTimestamp),
    debuggerActive: false,
  };
  return { ...base, ...fields };
};
