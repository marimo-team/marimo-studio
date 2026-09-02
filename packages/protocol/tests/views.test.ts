import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { parseCreatedView, viewNameError, viewNameSchema } from "../src/views.ts";

test("view names use the portable backend contract", () => {
  const maximumName = "a".repeat(240);
  assert.equal(viewNameError(maximumName), undefined);
  assert.deepEqual(parseCreatedView({ schema: 1, name: maximumName }), {
    schema: 1,
    name: maximumName,
  });

  const invalid = [
    [
      "Bad View",
      "View names must start with a lowercase letter and contain lowercase letters, digits, or hyphens.",
    ],
    ["api", "View name 'api' is reserved."],
    ["con", "View name contains a reserved Windows device name"],
    ["lpt9", "View name contains a reserved Windows device name"],
    ["a".repeat(241), "View name exceeds the 240-byte limit"],
  ] as const;

  for (const [name, message] of invalid) {
    assert.equal(viewNameError(name), message);
    const parsed = viewNameSchema.safeParse(name);
    assert.equal(parsed.success, false);
    if (!parsed.success) {
      assert.equal(parsed.error.issues[0]?.message, message);
    }
    assert.throws(() => parseCreatedView({ schema: 1, name }));
  }
});
