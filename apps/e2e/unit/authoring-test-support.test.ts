import { expect, test } from "vite-plus/test";

import { readBrowserValidation } from "../tests/authoring-test-support.ts";

const report = (state: "not-observed" | "stale") =>
  JSON.stringify({
    ok: false,
    stages: {
      browser: {
        observations: [
          {
            client_id: "browser-client-1234",
            state,
            projection_instances: [],
          },
        ],
      },
    },
  });

test("accepts public nonterminal browser validation states", () => {
  expect(readBrowserValidation(report("not-observed")).stages.browser.observations[0]?.state).toBe(
    "not-observed",
  );
  expect(readBrowserValidation(report("stale")).stages.browser.observations[0]?.state).toBe(
    "stale",
  );
});
