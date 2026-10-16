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

  for (const name of ["Bad View", "api", "con", "lpt9", "a".repeat(241)]) {
    const message = viewNameError(name);
    assert.ok(message, name);
    const parsed = viewNameSchema.safeParse(name);
    assert.equal(parsed.success, false);
    if (!parsed.success) {
      assert.equal(parsed.error.issues[0]?.message, message);
    }
    assert.throws(() => parseCreatedView({ schema: 1, name }));
  }
});
