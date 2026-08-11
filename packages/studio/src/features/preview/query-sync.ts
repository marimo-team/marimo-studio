import { publicNotebookQuery, QUERY_OPERATION_QUERY_PARAM } from "@marimo-studio/protocol/query";

type QueryListener = (query: string, operationId?: string, completed?: boolean) => void;

interface QueryObserver {
  subscribe(listener: QueryListener): () => void;
}

type ObservedWindow = Window & {
  __MARIMO_STUDIO_QUERY_OBSERVER__?: QueryObserver;
};

export const observeFrameQuery = (
  frame: HTMLIFrameElement,
  onQuery: QueryListener,
): (() => void) => {
  let unsubscribe: (() => void) | undefined;
  const install = () => {
    const child = frame.contentWindow as ObservedWindow | null;
    if (!child) {
      return;
    }
    try {
      unsubscribe?.();
      const observer = child.__MARIMO_STUDIO_QUERY_OBSERVER__ ?? createObserver(child);
      child.__MARIMO_STUDIO_QUERY_OBSERVER__ = observer;
      unsubscribe = observer.subscribe(onQuery);
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
  return () => {
    frame.removeEventListener("load", install);
    unsubscribe?.();
    unsubscribe = undefined;
  };
};

const createObserver = (child: Window): QueryObserver => {
  const listeners = new Set<QueryListener>();
  let activeOperation: string | undefined;
  const query = () => publicNotebookQuery(child.location.search);
  const notify = (operationId?: string, completed = false) => {
    listeners.forEach((listener) => listener(query(), operationId, completed));
  };
  const pushState = child.history.pushState.bind(child.history);
  const replaceState = child.history.replaceState.bind(child.history);
  const navigate = (
    writer: History["pushState"],
    data: unknown,
    unused: string,
    url?: string | URL | null,
  ) => {
    if (url === undefined || url === null) {
      writer(data, unused, url);
      notify();
      return;
    }
    const target = new URL(String(url), child.location.href);
    const operationId = target.searchParams.get(QUERY_OPERATION_QUERY_PARAM) ?? undefined;
    target.searchParams.delete(QUERY_OPERATION_QUERY_PARAM);
    const destination = `${target.pathname}${target.search}${target.hash}`;
    if (operationId !== undefined) {
      activeOperation = operationId;
      if (target.href !== child.location.href) {
        writer(data, unused, destination);
      }
      notify(operationId);
      return;
    }
    if (activeOperation !== undefined) {
      const operation = activeOperation;
      if (target.href !== child.location.href) {
        writer(data, unused, destination);
        notify(operation);
      } else {
        activeOperation = undefined;
        notify(operation, true);
      }
      return;
    }
    writer(data, unused, destination);
    notify();
  };
  const initial = new URL(child.location.href);
  activeOperation = initial.searchParams.get(QUERY_OPERATION_QUERY_PARAM) ?? undefined;
  if (activeOperation !== undefined) {
    initial.searchParams.delete(QUERY_OPERATION_QUERY_PARAM);
    replaceState({}, "", `${initial.pathname}${initial.search}${initial.hash}`);
  }
  child.history.pushState = (data, unused, url) => {
    navigate(pushState, data, unused, url);
  };
  child.history.replaceState = (data, unused, url) => {
    navigate(replaceState, data, unused, url);
  };
  child.addEventListener("popstate", () => notify());
  return {
    subscribe(listener) {
      listeners.add(listener);
      listener(query(), activeOperation, false);
      return () => listeners.delete(listener);
    },
  };
};
