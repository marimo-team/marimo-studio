export interface RuntimeTransport<SessionId> {
  getWsURL(sessionId: SessionId): URL;
  getSseURL(sessionId: SessionId): URL;
}

const configuredTransports = new WeakSet<object>();

export const configureKioskTransport = <SessionId>(
  runtime: RuntimeTransport<SessionId>,
  editMode: boolean,
) => {
  if (!editMode || configuredTransports.has(runtime)) {
    return;
  }
  configuredTransports.add(runtime);
  const kiosk = (url: URL) => {
    url.searchParams.set("kiosk", "true");
    return url;
  };
  const getWsURL = runtime.getWsURL.bind(runtime);
  const getSseURL = runtime.getSseURL.bind(runtime);

  runtime.getWsURL = (sessionId) => kiosk(getWsURL(sessionId));
  runtime.getSseURL = (sessionId) => kiosk(getSseURL(sessionId));
};
