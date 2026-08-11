type ProjectionListener = () => void;

const listeners = new Set<ProjectionListener>();

export const notifyProjectionChanged = (): void => {
  listeners.forEach((listener) => listener());
};

export const subscribeProjectionChanges = (listener: ProjectionListener): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
