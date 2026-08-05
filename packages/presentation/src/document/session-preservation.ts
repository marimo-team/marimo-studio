import type { RuntimeConfig } from "../runtime-config/index.ts";

type NavigationType = PerformanceNavigationTiming["type"];

export interface SessionEnvironment {
  href: string;
  navigationType: NavigationType | undefined;
  replaceUrl: (url: string) => void;
  storage: Pick<Storage, "getItem" | "removeItem" | "setItem">;
}

const SESSION_ID_PATTERN = /^s_[\da-z]{6}$/;
const DOCUMENT_REPLAY_PARAM = "marimo_studio_resume";

interface ServerSessionConfig {
  fileKey: string;
  preserve: boolean;
}

const serverSessionConfig = (config: RuntimeConfig): ServerSessionConfig | undefined => {
  if (config.runtime.id !== "server") {
    return undefined;
  }
  const fileKey = config.runtime.data.fileKey;
  const preserve = config.runtime.data.preserveSession;
  if (typeof fileKey !== "string" || typeof preserve !== "boolean") {
    return undefined;
  }
  return { fileKey, preserve };
};

const browserEnvironment = (): SessionEnvironment => {
  const navigation = performance.getEntriesByType("navigation")[0] as
    | PerformanceNavigationTiming
    | undefined;
  return {
    href: globalThis.location.href,
    navigationType: navigation?.type,
    replaceUrl: (url) => globalThis.history.replaceState(history.state, "", url),
    storage: globalThis.sessionStorage,
  };
};

const storageKey = (config: RuntimeConfig, url: URL): string => {
  const runtime = serverSessionConfig(config);
  return `marimo-studio:session:v1:server:${runtime?.fileKey ?? "unknown"}:${url.pathname}`;
};

export const prepareSessionRefresh = (
  config: RuntimeConfig,
  environment?: SessionEnvironment,
): boolean => {
  try {
    const browser = environment ?? browserEnvironment();
    const url = new URL(browser.href);
    const runtime = serverSessionConfig(config);
    if (!runtime || !runtime.preserve || config.mode !== "run") {
      if (runtime) {
        browser.storage.removeItem(storageKey(config, url));
      }
      if (url.searchParams.has(DOCUMENT_REPLAY_PARAM)) {
        url.searchParams.delete("session_id");
        url.searchParams.delete(DOCUMENT_REPLAY_PARAM);
        browser.replaceUrl(url.toString());
      }
      return false;
    }
    const explicit = url.searchParams.get("session_id");
    if (
      url.searchParams.get(DOCUMENT_REPLAY_PARAM) === "1" &&
      explicit &&
      SESSION_ID_PATTERN.test(explicit)
    ) {
      return true;
    }
    if (browser.navigationType !== "reload") {
      return false;
    }
    if (explicit && SESSION_ID_PATTERN.test(explicit)) {
      url.searchParams.set(DOCUMENT_REPLAY_PARAM, "1");
      browser.replaceUrl(url.toString());
      return true;
    }
    const remembered = browser.storage.getItem(storageKey(config, url));
    if (remembered && SESSION_ID_PATTERN.test(remembered)) {
      url.searchParams.set("session_id", remembered);
      url.searchParams.set(DOCUMENT_REPLAY_PARAM, "1");
      browser.replaceUrl(url.toString());
      return true;
    } else if (explicit !== null) {
      url.searchParams.delete("session_id");
      browser.replaceUrl(url.toString());
    }
  } catch {
    return false;
  }
  return false;
};

export const preservedDocumentUrl = (
  config: RuntimeConfig,
  target: string,
  sessionId: string | undefined,
  href = globalThis.location.href,
): string => {
  const url = new URL(target, href);
  const current = new URL(href);
  const runtimeSelection = current.searchParams.get("runtime");
  if (runtimeSelection && !url.searchParams.has("runtime")) {
    url.searchParams.set("runtime", runtimeSelection);
  }
  const runtime = serverSessionConfig(config);
  if (
    runtime?.preserve &&
    config.mode === "run" &&
    sessionId &&
    SESSION_ID_PATTERN.test(sessionId)
  ) {
    url.searchParams.set("session_id", sessionId);
    url.searchParams.set(DOCUMENT_REPLAY_PARAM, "1");
  }
  return url.toString();
};

export const finishSessionRefresh = (
  environment?: Pick<SessionEnvironment, "href" | "replaceUrl">,
): void => {
  try {
    const browser = environment ?? browserEnvironment();
    const url = new URL(browser.href);
    if (!url.searchParams.has(DOCUMENT_REPLAY_PARAM)) {
      return;
    }
    url.searchParams.delete("session_id");
    url.searchParams.delete(DOCUMENT_REPLAY_PARAM);
    browser.replaceUrl(url.toString());
  } catch {
    return;
  }
};

export const rememberSession = (
  config: RuntimeConfig,
  sessionId: string,
  environment?: SessionEnvironment,
): void => {
  const runtime = serverSessionConfig(config);
  if (!runtime?.preserve || config.mode !== "run" || !SESSION_ID_PATTERN.test(sessionId)) {
    return;
  }
  try {
    const browser = environment ?? browserEnvironment();
    const url = new URL(browser.href);
    browser.storage.setItem(storageKey(config, url), sessionId);
  } catch {
    return;
  }
};
