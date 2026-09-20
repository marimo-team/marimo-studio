import { resolve } from "node:path";

import { withExportRepository } from "../scripts/export-repository.mjs";
import { providerConfigDirectory } from "../scripts/paths.mjs";
import { ProviderWorkspace } from "../scripts/provider-workspace.mjs";
import { test as base } from "./network-fixture.ts";

export const test = base.extend<
  {},
  {
    providerViews: readonly (
      | "overview"
      | "gallery"
      | "story"
      | "slides"
      | "notebook"
      | "web"
      | "dashboard"
    )[];
    providerWorkspace: ProviderWorkspace;
  }
>({
  providerViews: [["overview", "gallery", "story"], { scope: "worker", option: true }],
  providerWorkspace: [
    async ({ providerViews, network: _network }, use) =>
      withExportRepository(resolve(providerConfigDirectory, "export-repository"), async () => {
        const workspace = new ProviderWorkspace();
        const failures: unknown[] = [];
        try {
          await workspace.prepare(providerViews);
          await use(workspace);
        } catch (error) {
          failures.push(error);
        }
        try {
          await workspace.close();
        } catch (error) {
          failures.push(error);
        }
        if (failures.length === 1) throw failures[0];
        if (failures.length > 1) {
          throw new AggregateError(failures, "Provider workspace setup and teardown failed");
        }
      }),
    { scope: "worker", auto: true, timeout: 420_000 },
  ],
});
