type RuntimeConnectionState = "connecting" | "ready" | "error";
export type PageReadinessState = "connecting" | "loading" | "ready" | "error";

interface MarimoStudioApi {
  ready: () => Promise<void>;
}

interface Deferred {
  promise: Promise<void>;
  resolve: () => void;
}

const deferred = (): Deferred => {
  let resolve = () => {};
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

let connectionState: RuntimeConnectionState = "connecting";
let waiter = deferred();
let settled = false;
let observer: MutationObserver | undefined;

const hostState = (host: Element): string => {
  return (host as HTMLElement).dataset.state ?? "connecting";
};

export const pageReadinessState = (
  connection: RuntimeConnectionState,
  hostStates: string[],
): PageReadinessState => {
  if (connection === "error") {
    return "error";
  }
  if (connection !== "ready") {
    return "connecting";
  }
  if (
    hostStates.some((state) => ["connecting", "loading"].includes(state))
  ) {
    return "loading";
  }
  if (hostStates.some((state) => ["error", "missing"].includes(state))) {
    return "error";
  }
  return "ready";
};

const evaluate = () => {
  const cells = Array.from(document.querySelectorAll("marimo-cell"));
  const values = Array.from(document.querySelectorAll("[mo-value]"));
  const hosts = [...cells, ...values];
  const next = pageReadinessState(connectionState, hosts.map(hostState));

  document.documentElement.dataset.marimoStudioState = next;
  const nextSettled = next === "ready" || next === "error";
  if (!nextSettled && settled) {
    waiter = deferred();
  }
  if (nextSettled && !settled) {
    waiter.resolve();
    document.dispatchEvent(
      new CustomEvent("marimo-studio:idle", {
        detail: { state: next },
      }),
    );
  }
  settled = nextSettled;
};

export const notifyReadinessChanged = () => {
  queueMicrotask(evaluate);
};

export const setRuntimeConnectionState = (
  state: RuntimeConnectionState,
) => {
  const previous = connectionState;
  connectionState = state;
  if (state === "ready" && previous !== "ready") {
    document.dispatchEvent(new CustomEvent("marimo-studio:runtime-ready"));
  }
  notifyReadinessChanged();
};

export const startReadiness = () => {
  document.documentElement.dataset.marimoStudioState = "connecting";
  globalThis.marimoStudio = {
    ready: () => {
      evaluate();
      return settled ? Promise.resolve() : waiter.promise;
    },
  };
  observer?.disconnect();
  observer = new MutationObserver(notifyReadinessChanged);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-state", "mo-value", "name"],
    childList: true,
    subtree: true,
  });
  notifyReadinessChanged();
};

declare global {
  var marimoStudio: MarimoStudioApi;

  interface Window {
    marimoStudio: MarimoStudioApi;
  }
}
