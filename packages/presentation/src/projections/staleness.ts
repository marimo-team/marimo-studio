const STALE_BINDING_EVENT = "marimo-studio:projection-binding-stale";

interface ProjectionFailure {
  readonly code: string;
  readonly transient: boolean;
}

let staleProjectionRevision: string | undefined;

export const projectionBindingIsStale = (projectionRevision: string): boolean =>
  projectionRevision === staleProjectionRevision;

export const clearProjectionBindingStale = (projectionRevision: string): void => {
  if (staleProjectionRevision === projectionRevision) {
    staleProjectionRevision = undefined;
  }
};

export const notifyProjectionBindingStale = (
  failure: ProjectionFailure,
  projectionRevision: string,
): void => {
  if (failure.code === "stale-projection-binding" && !failure.transient) {
    notifyProjectionResolutionStale(projectionRevision);
  }
};

export const notifyProjectionResolutionStale = (projectionRevision: string): void => {
  if (staleProjectionRevision === projectionRevision) {
    return;
  }
  staleProjectionRevision = projectionRevision;
  document.dispatchEvent(new Event(STALE_BINDING_EVENT));
};

export const bindProjectionBindingStale = (callback: () => void): (() => void) => {
  document.addEventListener(STALE_BINDING_EVENT, callback);
  return () => document.removeEventListener(STALE_BINDING_EVENT, callback);
};
