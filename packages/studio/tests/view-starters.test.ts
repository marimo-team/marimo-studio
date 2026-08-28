import { expect, it } from "vite-plus/test";

import { groupStartersByDistribution, preferredStarterId } from "../src/features/views/starters.ts";
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

it("groups provider entry points by registering distribution in catalog order", () => {
  const reportStarter = {
    ...componentStarter,
    id: "acme-views/report:default",
    provider: "acme-views/report",
    title: "Report",
  };

  expect(groupStartersByDistribution([componentStarter, reportStarter, starter])).toEqual([
    {
      distribution: "acme-views",
      starters: [componentStarter, reportStarter],
    },
    {
      distribution: "marimo-studio",
      starters: [starter],
    },
  ]);
});
