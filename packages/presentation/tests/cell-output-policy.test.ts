import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { filterCellLogs } from "../src/runtime/cells/cell-output-policy.ts";

test("cell log filtering preserves interactive and structured output channels", () => {
  const outputs = [
    { channel: "stdout", data: "progress" },
    { channel: "stderr", data: "warning" },
    { channel: "stdin", data: "prompt" },
    { channel: "pdb", data: "debugger" },
    { channel: "media", data: "plot" },
    { channel: "marimo-error", data: "error" },
  ];

  assert.equal(filterCellLogs(outputs, true), outputs);
  assert.deepEqual(filterCellLogs(outputs, false), outputs.slice(2));
});
