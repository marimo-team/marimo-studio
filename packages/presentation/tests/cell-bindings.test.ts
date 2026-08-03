import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { indexCells, resolveCellBinding } from "../src/cells/bindings.ts";

const cells = [
  { id: "MJUe", name: "controls" },
  { id: "bkHC", name: "summary" },
  { id: "lEQa", name: "revenue_table" },
  { id: "nCbo", name: "xy" },
];

test("bindings resolve against the live notebook identity", () => {
  const anonymous = { id: "PKri", name: "_" };
  const index = indexCells([...cells, anonymous]);
  assert.strictEqual(resolveCellBinding({ kind: "name", value: "revenue_table" }, index), cells[2]);
  assert.deepEqual(resolveCellBinding({ kind: "name", value: "xy" }, index)?.id, "nCbo");
  assert.strictEqual(resolveCellBinding({ kind: "id", value: "PKri" }, index), anonymous);
  assert.deepEqual(resolveCellBinding({ kind: "name", value: "missing" }, index), undefined);
});
