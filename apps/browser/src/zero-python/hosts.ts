export interface AuthoredProjectionHosts {
  readonly cells: readonly string[];
  readonly outputs: readonly string[];
  readonly values: readonly string[];
}

export const authoredProjectionHosts = (runtimeRoot: HTMLElement): AuthoredProjectionHosts => {
  const shell = runtimeRoot.ownerDocument.querySelector("#app-shell");
  if (shell === null) {
    throw new Error("The prepared presentation is missing its authored application shell.");
  }
  const values = (selector: string, attribute: string): readonly string[] =>
    Array.from(shell.querySelectorAll<HTMLElement>(selector))
      .filter(
        (element) =>
          element.parentElement?.closest("marimo-cell, marimo-output, [mo-value]") === null,
      )
      .flatMap((element) => {
        const value = element.getAttribute(attribute);
        return value === null ? [] : [value];
      });
  return Object.freeze({
    cells: Object.freeze([...new Set(values("marimo-cell[name]", "name"))]),
    outputs: Object.freeze([...new Set(values("marimo-output[value]", "value"))]),
    values: Object.freeze([...new Set(values("[mo-value]", "mo-value"))]),
  });
};
