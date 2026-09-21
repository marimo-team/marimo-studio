import { startRenderedViewObserver, stopRenderedViewObserver } from "./rendered-view-observer.ts";

export const startPresentationObservers = (updateQuery: (query: string) => Promise<void>): void => {
  startRenderedViewObserver(updateQuery);
};

export const stopPresentationObservers = (): void => {
  stopRenderedViewObserver();
};
