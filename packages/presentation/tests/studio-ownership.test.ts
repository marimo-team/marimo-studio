import { expect, test } from "vite-plus/test";

import { studioOwned } from "../src/document/studio-ownership.ts";

test("Studio ownership requires its client and document lifecycle", () => {
  expect(studioOwned({})).toBe(false);
  expect(studioOwned({ clientId: "client-123456789" })).toBe(false);
  expect(studioOwned({ lifecycleId: 7 })).toBe(false);
  expect(studioOwned({ clientId: "client-123456789", lifecycleId: 7 })).toBe(true);
});
