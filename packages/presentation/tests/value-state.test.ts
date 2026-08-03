import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { ValueStates } from "../src/values/state.ts";

test("a host connected during a value refresh inherits the pending phase", () => {
  const states = new ValueStates();

  assert.deepEqual(states.connected("context", false), {
    phase: "connecting",
  });
  states.pending("context", false);
  assert.deepEqual(states.connected("context", false), {
    phase: "loading",
  });

  states.resolved("context");
  states.pending("context", true);
  assert.deepEqual(states.connected("context", true), {
    phase: "stale",
  });

  states.clear("context");
  assert.deepEqual(states.connected("context", false), {
    phase: "connecting",
  });
});
