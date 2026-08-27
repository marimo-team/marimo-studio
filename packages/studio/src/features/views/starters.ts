import type { Starter } from "@marimo-studio/protocol/provider-catalog";

export const preferredStarterId = (
  starters: readonly Starter[],
  defaultStarter: string,
): string => {
  const advertised = starters.find(
    (starter) => starter.id === defaultStarter && starter.availability.available,
  );
  return (
    advertised?.id ??
    starters.find((starter) => starter.availability.available)?.id ??
    starters.find((starter) => starter.id === defaultStarter)?.id ??
    starters[0]?.id ??
    ""
  );
};
