import type { CellDiagnostic } from "./cell-projection";

export const CellFallback = ({
  alias,
  developer,
  diagnostic,
  variant,
}: {
  alias: string;
  developer: boolean;
  diagnostic?: CellDiagnostic;
  variant: "disabled" | "missing";
}) => {
  if (variant === "disabled") {
    return (
      <div className="marimo-cell-error" role="alert">
        Cell alias <code>{alias}</code> is disabled in the notebook graph.
      </div>
    );
  }

  const message = developer
    ? (diagnostic?.message ?? `Cell ${JSON.stringify(alias)} is unavailable.`)
    : "This section is unavailable.";
  return (
    <div className="marimo-cell-diagnostic" role="status">
      <strong>{message}</strong>
      {developer && diagnostic?.hint ? <span>{diagnostic.hint}</span> : null}
    </div>
  );
};
