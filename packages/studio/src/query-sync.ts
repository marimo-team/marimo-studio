import { publicNotebookQuery } from "@marimo-studio/protocol/query";

type ObservedWindow = Window & {
  __MARIMO_STUDIO_QUERY_OBSERVER__?: true;
};

export const observeFrameQuery = (
  frame: HTMLIFrameElement,
  onQuery: (query: string) => void,
): (() => void) => {
  const install = () => {
    const child = frame.contentWindow as ObservedWindow | null;
    if (!child) {
      return;
    }
    try {
      const notify = () => onQuery(publicNotebookQuery(child.location.search));
      if (child.__MARIMO_STUDIO_QUERY_OBSERVER__) {
        notify();
        return;
      }
      child.__MARIMO_STUDIO_QUERY_OBSERVER__ = true;
      const pushState = child.history.pushState.bind(child.history);
      const replaceState = child.history.replaceState.bind(child.history);
      child.history.pushState = (...arguments_) => {
        pushState(...arguments_);
        notify();
      };
      child.history.replaceState = (...arguments_) => {
        replaceState(...arguments_);
        notify();
      };
      child.addEventListener("popstate", notify);
      notify();
    } catch {
      return;
    }
  };

  frame.addEventListener("load", install);
  try {
    if (
      frame.contentDocument?.readyState === "complete" &&
      frame.contentWindow?.location.href !== "about:blank"
    ) {
      install();
    }
  } catch {
    return () => frame.removeEventListener("load", install);
  }
  return () => frame.removeEventListener("load", install);
};
