import { expect, it } from "vite-plus/test";

import { preferredStarterId } from "../src/features/views/starters.ts";
import { starter, componentStarter } from "./fixtures.ts";

it("selects the advertised default independently of catalog order", () => {
  expect(preferredStarterId([componentStarter, starter], starter.id)).toBe(
    "marimo-studio/vanilla:default",
  );
});

it("selects an available starter when the advertised default is unavailable", () => {
  const unavailableDefault = {
    ...starter,
    availability: {
      available: false,
      version: null,
      reason: "Unavailable",
      action: "Install support",
    },
  };

  expect(preferredStarterId([unavailableDefault, componentStarter], unavailableDefault.id)).toBe(
    "acme-views/component:default",
  );
});
