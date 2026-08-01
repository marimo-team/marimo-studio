import { createRequire } from "node:module";
import { dirname, join } from "node:path";

/** Resolve a dependency from the package that declares it. */
export const resolveOwnedDependency = (
  project: string,
  owner: string,
  dependency: string,
): string => {
  const projectRequire = createRequire(join(project, "package.json"));
  const ownerEntry = projectRequire.resolve(owner);
  const dependencyEntry = createRequire(ownerEntry).resolve(dependency);
  return dirname(dirname(dependencyEntry));
};
