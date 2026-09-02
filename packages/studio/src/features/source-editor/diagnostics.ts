import type {
  ProjectDiagnostic,
  ProjectSourceLocation,
} from "@marimo-studio/protocol/view-project";

export const highestSeverityDiagnostic = (
  diagnostics: readonly ProjectDiagnostic[],
  path?: ProjectSourceLocation["path"],
): ProjectDiagnostic | undefined => {
  const matching =
    path === undefined
      ? diagnostics
      : diagnostics.filter((diagnostic) => diagnostic.source?.path === path);
  return matching.find((diagnostic) => diagnostic.severity === "error") ?? matching.at(0);
};
