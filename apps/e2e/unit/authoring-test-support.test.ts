import { expect, test } from "vite-plus/test";

import { readBrowserAnalysis } from "../tests/authoring-test-support.ts";

const report = (state: "not-observed" | "stale") =>
  JSON.stringify({
    handoff_ready: false,
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

test("accepts public nonterminal browser analysis states", () => {
  expect(readBrowserAnalysis(report("not-observed")).stages.browser.observations[0]?.state).toBe(
    "not-observed",
  );
  expect(readBrowserAnalysis(report("stale")).stages.browser.observations[0]?.state).toBe("stale");
});
