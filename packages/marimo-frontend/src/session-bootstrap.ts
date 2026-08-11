declare const sessionIdBrand: unique symbol;

export type SessionId = string & { readonly [sessionIdBrand]: true };

let sessionId: SessionId | undefined;
let sessionBootstrap: Promise<SessionId> | undefined;

export const isSessionId = (value: string | null | undefined): value is SessionId =>
  typeof value === "string" && /^s_[\da-z]{6}$/.test(value);

export const bootstrapSession = (preflight: () => void | Promise<void>): Promise<SessionId> => {
  if (sessionBootstrap) {
    return sessionBootstrap;
  }
  const pending = (async () => {
    await preflight();
    const { getSessionId } = await import("./upstream/session.ts");
    sessionId = getSessionId() as unknown as SessionId;
    return sessionId;
  })();
  sessionBootstrap = pending;
  void pending.catch(() => {
    if (sessionBootstrap === pending) {
      sessionBootstrap = undefined;
    }
  });
  return pending;
};

export const currentSessionId = (): SessionId => {
  if (!sessionId) {
    throw new Error("The Marimo session has not been bootstrapped");
  }
  return sessionId;
};
