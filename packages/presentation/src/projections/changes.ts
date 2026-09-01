type ProjectionListener = () => void;

const listeners = new Set<ProjectionListener>();
let notificationPending = false;

export const notifyProjectionChanged = (): void => {
  if (notificationPending) {
    return;
  }
  notificationPending = true;
  queueMicrotask(() => {
    notificationPending = false;
    listeners.forEach((listener) => listener());
  });
};

export const subscribeProjectionChanges = (listener: ProjectionListener): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
