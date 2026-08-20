import { expect, it } from "vite-plus/test";

import { runtimeStartupRecovery } from "../src/runtime-config/startup-recovery.ts";

it("reloads when the initial presentation revision cannot be admitted", () => {
  expect(runtimeStartupRecovery("presentation-revision-mismatch")).toBe("reload");
  expect(runtimeStartupRecovery("presentation-revision-unavailable")).toBe("reload");
  expect(runtimeStartupRecovery("runtime-sync-pending")).toBe("retry");
});
