import { expect, test } from "vite-plus/test";

import { processEnvironmentContains } from "../scripts/process-group.ts";

test("treats an unreadable Linux process environment as unknown", () => {
  const readFailure = Object.assign(new Error("permission denied"), { code: "EACCES" });

  expect(
    processEnvironmentContains(123, "OWNER", "nonce", {
      platform: "linux",
      readFile: () => {
        throw readFailure;
      },
    }),
  ).toBeUndefined();
});
