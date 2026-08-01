import { createRequire } from "node:module";
import { dirname, join } from "node:path";

/** Resolve a dependency entry from the package that declares it. */
export const resolveProjectDependency = (
  project: string,
  dependency: string,
): string => {
  return createRequire(join(project, "package.json")).resolve(dependency);
};

/** Resolve a dependency from the package that declares it. */
export const resolveOwnedDependency = (
  project: string,
  owner: string,
  dependency: string,
): string => {
  const ownerEntry = resolveProjectDependency(project, owner);
  const dependencyEntry = createRequire(ownerEntry).resolve(dependency);
  return dirname(dirname(dependencyEntry));
};
