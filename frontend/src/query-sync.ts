const PRIVATE_QUERY_KEYS = [
  "access_token",
  "file",
  "kiosk",
  "marimo_studio_resume",
  "refresh_token",
  "session_id",
] as const;

export const publicNotebookQuery = (search: string): string => {
  const parameters = new URLSearchParams(search);
  for (const key of PRIVATE_QUERY_KEYS) {
    parameters.delete(key);
  }
  const query = parameters.toString();
  return query ? `?${query}` : "";
};

type ObservedWindow = Window & {
  __MARIMO_STUDIO_QUERY_OBSERVER__?: true;
};

export const observeFrameQuery = (
  frame: HTMLIFrameElement,
  onQuery: (query: string) => void,
): () => void => {
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

export const startQuerySync = (): void => {
  const frame = globalThis.frameElement;
  if (
    frame?.localName !== "iframe" ||
    !frame.hasAttribute("data-preview-frame")
  ) {
    return;
  }
  const notify = () => {
    globalThis.parent.postMessage(
      {
        type: "marimo-studio:query-change",
        query: publicNotebookQuery(globalThis.location.search),
      },
      globalThis.location.origin,
    );
  };
  const pushState = globalThis.history.pushState.bind(globalThis.history);
  const replaceState = globalThis.history.replaceState.bind(
    globalThis.history,
  );

  // Marimo applies mo.query_params() updates through same-document history
  // writes, which do not emit popstate events.
  globalThis.history.pushState = (...arguments_) => {
    pushState(...arguments_);
    notify();
  };
  globalThis.history.replaceState = (...arguments_) => {
    replaceState(...arguments_);
    notify();
  };
  globalThis.addEventListener("popstate", notify);
  notify();
};
