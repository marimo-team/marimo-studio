export const createSessionBootstrap = <SessionId>(
  loadSession: (authorized: SessionId | undefined) => Promise<SessionId>,
) => {
  let state: { status: "pending" } | { status: "ready"; sessionId: SessionId } = {
    status: "pending",
  };
  let sessionBootstrap: Promise<SessionId> | undefined;

  // Preflight returns the URL session it validated, if any.
  const bootstrap = (
    preflight: () => SessionId | undefined | void | Promise<SessionId | undefined | void>,
  ): Promise<SessionId> => {
    if (sessionBootstrap) {
      return sessionBootstrap;
    }
    const pending = (async () => {
      const sessionId = await loadSession((await preflight()) ?? undefined);
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
