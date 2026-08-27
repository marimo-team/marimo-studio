import type { StarterCatalogState } from "./catalog.ts";

export const StarterCatalogNotice = ({
  catalog,
  empty,
  onRetry,
}: {
  catalog: StarterCatalogState;
  empty: boolean;
  onRetry: () => void;
}) => {
  if (catalog.phase === "error") {
    return (
      <div className="studio-starter-catalog-error" role="alert">
        <span>{catalog.message}</span>
        <button type="button" className="studio-control" onClick={onRetry}>
          Retry authoring options
        </button>
      </div>
    );
  }
  if (empty && catalog.phase === "ready") {
    return <p className="studio-form-hint">No view starters are available.</p>;
  }
  if (empty) {
    return (
      <p className="studio-form-hint" role="status" aria-live="polite">
        Loading installed authoring options…
      </p>
    );
  }
  return null;
};
