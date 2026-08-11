import { startAgentObserver, stopAgentObserver } from "./agent-observer.ts";
import { startRenderedViewObserver, stopRenderedViewObserver } from "./rendered-view-observer.ts";

export const startPresentationObservers = (updateQuery: (query: string) => Promise<void>): void => {
  startRenderedViewObserver(updateQuery);
  startAgentObserver();
};

export const stopPresentationObservers = (): void => {
  stopAgentObserver();
  stopRenderedViewObserver();
};
