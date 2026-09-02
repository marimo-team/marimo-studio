import type { Starter } from "@marimo-studio/protocol/provider-catalog";

export interface StarterDistributionGroup {
  distribution: string;
  starters: readonly Starter[];
}

export const groupStartersByDistribution = (
  starters: readonly Starter[],
): readonly StarterDistributionGroup[] => {
  const groups = new Map<string, Starter[]>();
  for (const starter of starters) {
    const distribution = starter.provider.split("/", 1)[0]!;
    const group = groups.get(distribution);
    if (group) {
      group.push(starter);
    } else {
      groups.set(distribution, [starter]);
    }
  }
  return Array.from(groups, ([distribution, groupedStarters]) => ({
    distribution,
    starters: groupedStarters,
  }));
};

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
