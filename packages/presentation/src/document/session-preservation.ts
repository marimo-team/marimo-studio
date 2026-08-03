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
  return `marimo-studio:session:v1:${config.fileKey}:${url.pathname}`;
};

export const prepareSessionRefresh = (
  config: RuntimeConfig,
  environment?: SessionEnvironment,
): boolean => {
  try {
    const browser = environment ?? browserEnvironment();
    const url = new URL(browser.href);
    if (!config.preserveSession || config.mode !== "run") {
      browser.storage.removeItem(storageKey(config, url));
      if (url.searchParams.has(DOCUMENT_REPLAY_PARAM)) {
        url.searchParams.delete("session_id");
        url.searchParams.delete(DOCUMENT_REPLAY_PARAM);
        browser.replaceUrl(url.toString());
      }
      return false;
    }
    if (browser.navigationType !== "reload") {
      return false;
    }
    const explicit = url.searchParams.get("session_id");
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
  if (!config.preserveSession || config.mode !== "run" || !SESSION_ID_PATTERN.test(sessionId)) {
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
