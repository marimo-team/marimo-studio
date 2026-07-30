import { assertEquals } from "@std/assert";

import { ValueStates } from "../src/value-state.ts";

Deno.test("a host connected during a value refresh inherits the pending phase", () => {
  const states = new ValueStates();

  assertEquals(states.connected("context", false), {
    phase: "connecting",
  });
  states.pending("context", false);
  assertEquals(states.connected("context", false), {
    phase: "loading",
  });

  states.resolved("context");
  states.pending("context", true);
  assertEquals(states.connected("context", true), {
    phase: "stale",
  });
});
