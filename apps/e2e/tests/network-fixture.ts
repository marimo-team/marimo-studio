import { test as base } from "@playwright/test";

import { e2eNetwork } from "../scripts/network.mjs";

export const test = base.extend<{}, { network: typeof e2eNetwork }>({
  network: [
    async ({ browserName: _browserName }, use) => {
      try {
        await e2eNetwork.start();
        await use(e2eNetwork);
      } finally {
        await e2eNetwork.close();
      }
    },
    { scope: "worker", auto: true },
  ],
});
