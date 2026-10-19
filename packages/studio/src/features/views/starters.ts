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

/** Name what an unavailable starter needs, such as "Needs Quarto 1.9.38+". */
export const setupLabel = (starter: Starter): string =>
  starter.requirement ? `Needs ${starter.requirement}` : "Needs setup";

export const homepageHost = (homepage: string): string =>
  new URL(homepage).hostname.replace(/^www\./, "");

/** Return the URL of a starter's preview image, or undefined without one. */
export const starterPreviewUrl = (base: string, starter: Starter): string | undefined => {
  if (!starter.preview) {
    return undefined;
  }
  const url = new URL(base);
  url.searchParams.set("starter", starter.id);
  url.searchParams.set("revision", starter.preview);
  return url.toString();
};

export const matchesStarterQuery = (starter: Starter, query: string): boolean => {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) {
    return true;
  }
  const haystack = [
    starter.title,
    starter.summary,
    starter.format ?? "",
    starter.provider,
    ...starter.documents,
  ]
    .join(" ")
    .toLocaleLowerCase();
  return terms.every((term) => haystack.includes(term));
};
