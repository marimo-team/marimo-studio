import type { RuntimeProjectionRequest as ProjectionRequest } from "../../projections/resolution";
import type { ValueHostProjection } from "../../values/hosts";

export interface ValueGroup {
  key: string;
  projections: ProjectionRequest[];
  runtimeCellId: string | undefined;
  selectors: string[];
}

export const groupValueProjections = (
  projections: readonly ValueHostProjection[],
  projectionRevision: string,
): ValueGroup[] => {
  const groups = new Map<
    string,
    {
      projections: ProjectionRequest[];
      runtimeCellId: string | undefined;
      selectors: Set<string>;
    }
  >();
  projections.forEach(({ projection, request, projectionRevision: resolvedRevision }) => {
    if (resolvedRevision !== projectionRevision) {
      return;
    }
    const key = projection.producer;
    const group = groups.get(key) ?? {
      projections: [],
      runtimeCellId: projection.runtimeCellId,
      selectors: new Set<string>(),
    };
    if (!group.selectors.has(request.target)) {
      group.projections.push(request);
      group.selectors.add(request.target);
    }
    groups.set(key, group);
  });
  return Array.from(groups, ([key, group]) => ({
    key,
    projections: group.projections,
    runtimeCellId: group.runtimeCellId,
    selectors: Array.from(group.selectors).sort(),
  }));
};
