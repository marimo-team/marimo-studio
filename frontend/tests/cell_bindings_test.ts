import { assertEquals, assertStrictEquals } from "@std/assert";

import { indexCells, resolveCellBinding } from "../src/cell-bindings.ts";

const cells = [
  { id: "MJUe", name: "controls" },
  { id: "bkHC", name: "summary" },
  { id: "lEQa", name: "revenue_table" },
  { id: "nCbo", name: "xy" },
];

Deno.test("bindings resolve against the live notebook identity", () => {
  const anonymous = { id: "PKri", name: "_" };
  const index = indexCells([...cells, anonymous]);
  assertStrictEquals(
    resolveCellBinding(
      { kind: "name", value: "revenue_table" },
      index,
    ),
    cells[2],
  );
  assertEquals(
    resolveCellBinding({ kind: "name", value: "xy" }, index)?.id,
    "nCbo",
  );
  assertStrictEquals(
    resolveCellBinding({ kind: "id", value: "PKri" }, index),
    anonymous,
  );
  assertEquals(
    resolveCellBinding({ kind: "name", value: "missing" }, index),
    undefined,
  );
});
