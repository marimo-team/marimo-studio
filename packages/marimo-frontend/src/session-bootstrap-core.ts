export const createSessionBootstrap = <SessionId>(loadSession: () => Promise<SessionId>) => {
  let state: { status: "pending" } | { status: "ready"; sessionId: SessionId } = {
    status: "pending",
  };
  let sessionBootstrap: Promise<SessionId> | undefined;

  const bootstrap = (preflight: () => void | Promise<void>): Promise<SessionId> => {
    if (sessionBootstrap) {
      return sessionBootstrap;
    }
    const pending = (async () => {
      await preflight();
      const sessionId = await loadSession();
      state = { status: "ready", sessionId };
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

  const current = (): SessionId => {
    if (state.status !== "ready") {
      throw new Error("The Marimo session has not been bootstrapped");
    }
    return state.sessionId;
  };

  return { bootstrap, current };
};
