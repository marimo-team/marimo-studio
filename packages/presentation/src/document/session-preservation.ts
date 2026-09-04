import { isSessionId } from "@marimo-studio/marimo-frontend/session-bootstrap";
import {
  DOCUMENT_LIFECYCLE_QUERY_PARAM,
  DOCUMENT_REPLAY_QUERY_PARAM,
  PRESENTATION_RENEWAL_QUERY_PARAM,
  publicNotebookQuery,
  STUDIO_CLIENT_QUERY_PARAM,
} from "@marimo-studio/protocol/query";
import { z } from "zod";

import {
  getMountConfig,
  type RuntimeConfig,
  runtimeConfigSessionId,
} from "../runtime-config/index.ts";
import { serverRuntimeDataSchema } from "../runtime/server-config.ts";
import { studioOwned } from "./studio-ownership.ts";
import { setTrustedRuntimeQuery } from "./view-navigation.ts";

type NavigationType = PerformanceNavigationTiming["type"];

export interface SessionEnvironment {
  clientId?: string;
  href: string;
  lifecycleId?: number;
  navigationType: NavigationType | undefined;
  renewalToken?: string;
  replay: boolean;
  replaceUrl: (url: string) => void;
  runtimeExplicit: boolean;
  runtimeSessionId?: string;
  storage?: Pick<Storage, "getItem" | "removeItem" | "setItem">;
}

const navigationTypeSchema = z.enum(["navigate", "reload", "back_forward"]);

interface ServerSessionConfig {
  fileKey: string;
  preserve: boolean;
  sessionId: string;
}

const serverSessionConfig = (config: RuntimeConfig): ServerSessionConfig | undefined => {
  if (config.runtime.id !== "server") {
    return undefined;
  }
  const parsed = serverRuntimeDataSchema.safeParse(config.runtime.data);
  if (!parsed.success) {
    return undefined;
  }
  return {
    fileKey: parsed.data.fileKey,
    preserve: parsed.data.preserveSession,
    sessionId: parsed.data.sessionId,
  };
};

const storageUnavailable = (cause: unknown): boolean =>
  cause instanceof DOMException && cause.name === "SecurityError";

const browserStorage = (): SessionEnvironment["storage"] => {
  try {
    return globalThis.sessionStorage;
  } catch (cause) {
    if (storageUnavailable(cause)) {
      return undefined;
    }
    throw cause;
  }
};

const browserEnvironment = (): SessionEnvironment => {
  const navigation = performance.getEntriesByType("navigation")[0];
  const parsedNavigation = navigationTypeSchema.safeParse(
    navigation && "type" in navigation ? navigation.type : undefined,
  );
  return {
    clientId: getMountConfig().clientId,
    href: globalThis.location.href,
    lifecycleId: getMountConfig().lifecycleId,
    navigationType: parsedNavigation.success ? parsedNavigation.data : undefined,
    renewalToken: getMountConfig().renewalToken,
    replay: getMountConfig().replay,
    replaceUrl: (url) => globalThis.history.replaceState(history.state, "", url),
    runtimeExplicit: getMountConfig().runtimeExplicit,
    runtimeSessionId: getMountConfig().runtimeSessionId,
    storage: browserStorage(),
  };
};

const storagePrefix = (config: RuntimeConfig): string => {
  const runtime = serverSessionConfig(config);
  return `marimo-studio:session:v1:server:${runtime?.fileKey ?? "unknown"}`;
};

const publicQueryIdentity = (url: URL): string => {
  const query = new URLSearchParams(publicNotebookQuery(url.search));
  query.sort();
  return query.toString();
};

const pageStorageKey = (config: RuntimeConfig, url: URL, query: string): string => {
  return `${storagePrefix(config)}:page:${url.pathname}:${encodeURIComponent(query)}`;
};

const sessionStorageKey = (config: RuntimeConfig, sessionId: string): string => {
  return `${storagePrefix(config)}:session:${sessionId}`;
};

const sessionMatchesQuery = (
  config: RuntimeConfig,
  storage: NonNullable<SessionEnvironment["storage"]>,
  sessionId: string,
  query: string,
): boolean => storage.getItem(sessionStorageKey(config, sessionId)) === query;

const stripReplay = (url: URL): void => {
  url.searchParams.delete("session_id");
  url.searchParams.delete(DOCUMENT_REPLAY_QUERY_PARAM);
};

const isSameOriginRenewalDocument = (target: URL, current: URL): boolean => {
  if (target.origin !== current.origin) {
    return false;
  }
  const marker = "/_marimo-studio/presentation/";
  const boundary = target.pathname.lastIndexOf(marker);
  if (boundary < 0) {
    return false;
  }
  const capability = target.pathname.slice(boundary + marker.length).split("/", 1)[0];
  return capability?.startsWith("d.") === true;
};

const setStudioDocumentIdentity = (
  url: URL,
  identity: Pick<SessionEnvironment, "clientId" | "lifecycleId">,
  current = url,
): void => {
  if (!isSameOriginRenewalDocument(url, current)) {
    return;
  }
  url.searchParams.delete(STUDIO_CLIENT_QUERY_PARAM);
  url.searchParams.delete(DOCUMENT_LIFECYCLE_QUERY_PARAM);
  if (identity.clientId && identity.lifecycleId) {
    url.searchParams.set(STUDIO_CLIENT_QUERY_PARAM, identity.clientId);
    url.searchParams.set(DOCUMENT_LIFECYCLE_QUERY_PARAM, String(identity.lifecycleId));
  }
};

const setCurrentDocumentIdentity = (
  url: URL,
  identity: Pick<SessionEnvironment, "clientId" | "lifecycleId">,
): void => {
  url.searchParams.delete(STUDIO_CLIENT_QUERY_PARAM);
  url.searchParams.delete(DOCUMENT_LIFECYCLE_QUERY_PARAM);
  if (identity.clientId && identity.lifecycleId) {
    url.searchParams.set(STUDIO_CLIENT_QUERY_PARAM, identity.clientId);
    url.searchParams.set(DOCUMENT_LIFECYCLE_QUERY_PARAM, String(identity.lifecycleId));
  }
};

const serverAssignedDocumentSession = (
  config: RuntimeConfig,
  url: URL,
  authority: Pick<SessionEnvironment, "renewalToken">,
): { replaying: boolean } | undefined => {
  const runtime = serverSessionConfig(config);
  const sessions = url.searchParams.getAll("session_id");
  if (
    !runtime ||
    !authority.renewalToken ||
    sessions.length !== 1 ||
    !isSessionId(sessions[0]) ||
    sessions[0] !== runtime.sessionId
  ) {
    return undefined;
  }
  const replay = url.searchParams.getAll(DOCUMENT_REPLAY_QUERY_PARAM);
  if (replay.length === 0) {
    return { replaying: false };
  }
  return replay.length === 1 && replay[0] === "1" && config.mode === "run" && runtime.preserve
    ? { replaying: true }
    : undefined;
};

const preflightReplay = (config: RuntimeConfig, environment?: SessionEnvironment): boolean => {
  const browser = environment ?? browserEnvironment();
  const url = new URL(browser.href);
  const initialUrl = url.toString();
  const initialSessions = url.searchParams.getAll("session_id").filter(isSessionId);
  setTrustedRuntimeQuery(url, {
    id: config.runtime.id,
    explicit: browser.runtimeExplicit,
  });
  setCurrentDocumentIdentity(url, browser);
  url.searchParams.delete(PRESENTATION_RENEWAL_QUERY_PARAM);
  stripReplay(url);
  const runtime = serverSessionConfig(config);
  if (
    browser.renewalToken &&
    browser.runtimeSessionId &&
    runtime?.sessionId === browser.runtimeSessionId
  ) {
    url.searchParams.set("session_id", browser.runtimeSessionId);
    if (browser.replay) {
      url.searchParams.set(DOCUMENT_REPLAY_QUERY_PARAM, "1");
    }
  }
  const commitUrl = () => {
    const currentUrl = url.toString();
    if (currentUrl !== initialUrl) {
      browser.replaceUrl(currentUrl);
    }
  };
  const rejectUnavailableStorage = () => {
    const assigned = serverAssignedDocumentSession(config, url, browser);
    if (!assigned) {
      stripReplay(url);
    }
    commitUrl();
    return assigned?.replaying ?? false;
  };
  if (!browser.storage) {
    return rejectUnavailableStorage();
  }
  try {
    if (!runtime || !runtime.preserve || config.mode !== "run") {
      if (runtime) {
        const query = publicQueryIdentity(url);
        const key = pageStorageKey(config, url, query);
        const remembered = browser.storage.getItem(key);
        browser.storage.removeItem(key);
        const sessions = [remembered, ...initialSessions, browser.runtimeSessionId].filter(
          isSessionId,
        );
        for (const sessionId of sessions) {
          const sessionKey = sessionStorageKey(config, sessionId);
          const rememberedQuery = browser.storage.getItem(sessionKey);
          if (rememberedQuery !== null) {
            browser.storage.removeItem(pageStorageKey(config, url, rememberedQuery));
          }
          browser.storage.removeItem(sessionKey);
        }
      }
      if (url.searchParams.has(DOCUMENT_REPLAY_QUERY_PARAM)) {
        stripReplay(url);
      }
      commitUrl();
      return false;
    }
    const query = publicQueryIdentity(url);
    let explicit = url.searchParams.get("session_id");
    if (url.searchParams.get(DOCUMENT_REPLAY_QUERY_PARAM) === "1") {
      if (
        explicit &&
        isSessionId(explicit) &&
        sessionMatchesQuery(config, browser.storage, explicit, query)
      ) {
        commitUrl();
        return true;
      }
      stripReplay(url);
      explicit = null;
    }
    if (browser.navigationType !== "reload" && browser.navigationType !== "back_forward") {
      commitUrl();
      return false;
    }
    if (isSessionId(explicit)) {
      if (sessionMatchesQuery(config, browser.storage, explicit, query)) {
        url.searchParams.set(DOCUMENT_REPLAY_QUERY_PARAM, "1");
        commitUrl();
        return true;
      }
      url.searchParams.delete("session_id");
    }
    const pageKey = pageStorageKey(config, url, query);
    const remembered = browser.storage.getItem(pageKey);
    if (
      isSessionId(remembered) &&
      sessionMatchesQuery(config, browser.storage, remembered, query)
    ) {
      url.searchParams.set("session_id", remembered);
      url.searchParams.set(DOCUMENT_REPLAY_QUERY_PARAM, "1");
      commitUrl();
      return true;
    }
    browser.storage.removeItem(pageKey);
    commitUrl();
  } catch (cause) {
    if (storageUnavailable(cause)) {
      return rejectUnavailableStorage();
    }
    throw cause;
  }
  return false;
};

const replayDocumentUrl = (
  config: RuntimeConfig,
  target: string,
  sessionId: string | undefined,
  environment?: Pick<
    SessionEnvironment,
    "clientId" | "href" | "lifecycleId" | "runtimeExplicit" | "runtimeSessionId" | "storage"
  >,
): string => {
  const browser = environment ?? browserEnvironment();
  const href = browser.href;
  const url = new URL(target, href);
  const current = new URL(href);
  setTrustedRuntimeQuery(url, {
    id: config.runtime.id,
    explicit: browser.runtimeExplicit,
  });
  setStudioDocumentIdentity(url, browser, current);
  const runtime = serverSessionConfig(config);
  let authoritativeSession = runtime ? sessionId : undefined;
  if (browser.runtimeSessionId !== undefined) {
    authoritativeSession =
      runtime?.sessionId === browser.runtimeSessionId ? browser.runtimeSessionId : undefined;
  }
  if (
    config.mode === "edit" &&
    config.dev &&
    studioOwned(browser) &&
    authoritativeSession &&
    isSessionId(authoritativeSession) &&
    isSameOriginRenewalDocument(url, current)
  ) {
    stripReplay(url);
    url.searchParams.set("session_id", authoritativeSession);
    return url.toString();
  }
  let preserved = false;
  try {
    preserved = Boolean(
      browser.storage &&
      runtime?.preserve &&
      config.mode === "run" &&
      authoritativeSession &&
      isSessionId(authoritativeSession) &&
      sessionMatchesQuery(config, browser.storage, authoritativeSession, publicQueryIdentity(url)),
    );
  } catch (cause) {
    if (!storageUnavailable(cause)) {
      throw cause;
    }
  }
  if (preserved && authoritativeSession) {
    url.searchParams.set("session_id", authoritativeSession);
    url.searchParams.set(DOCUMENT_REPLAY_QUERY_PARAM, "1");
  } else {
    stripReplay(url);
  }
  return url.toString();
};

const finishReplay = (environment?: Pick<SessionEnvironment, "href" | "replaceUrl">): void => {
  try {
    const browser = environment ?? browserEnvironment();
    const url = new URL(browser.href);
    if (!url.searchParams.has(DOCUMENT_REPLAY_QUERY_PARAM)) {
      return;
    }
    url.searchParams.delete("session_id");
    url.searchParams.delete(DOCUMENT_REPLAY_QUERY_PARAM);
    browser.replaceUrl(url.toString());
  } catch {
    return;
  }
};

const replayPending = (environment?: Pick<SessionEnvironment, "href">): boolean => {
  try {
    const browser = environment ?? browserEnvironment();
    return new URL(browser.href).searchParams.get(DOCUMENT_REPLAY_QUERY_PARAM) === "1";
  } catch {
    return false;
  }
};

const rememberReplay = (
  config: RuntimeConfig,
  sessionId: string,
  environment?: SessionEnvironment,
): void => {
  const runtime = serverSessionConfig(config);
  if (!runtime?.preserve || config.mode !== "run" || !isSessionId(sessionId)) {
    return;
  }
  try {
    const browser = environment ?? browserEnvironment();
    if (!browser.storage) {
      return;
    }
    const url = new URL(browser.href);
    const sessionKey = sessionStorageKey(config, sessionId);
    const query = browser.storage.getItem(sessionKey) ?? publicQueryIdentity(url);
    browser.storage.setItem(sessionKey, query);
    browser.storage.setItem(pageStorageKey(config, url, query), sessionId);
  } catch (cause) {
    if (storageUnavailable(cause)) {
      return;
    }
    throw cause;
  }
};

export class BrowserSessionReplay {
  constructor(
    private readonly environment?: SessionEnvironment,
    private readonly currentSessionId: () => string | undefined = () =>
      runtimeConfigSessionId({ connected: globalThis.__MARIMO_STUDIO_SESSION_ID__ }),
  ) {}

  preflight(config: RuntimeConfig): boolean {
    return preflightReplay(config, this.environment);
  }

  pending(): boolean {
    return replayPending(this.environment);
  }

  preservedUrl(config: RuntimeConfig, target: string): string {
    return replayDocumentUrl(config, target, this.currentSessionId(), this.environment);
  }

  finish(): void {
    finishReplay(this.environment);
  }

  remember(config: RuntimeConfig, sessionId: string): void {
    rememberReplay(config, sessionId, this.environment);
  }
}

declare global {
  var __MARIMO_STUDIO_SESSION_ID__: string | undefined;
}
