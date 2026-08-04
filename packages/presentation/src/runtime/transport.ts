import { RUNTIME_QUERY_KEY } from "@marimo-studio/protocol/runtime-selection";

export interface RuntimeTransport<SessionId> {
  getWsURL(sessionId: SessionId): URL;
  getSseURL(sessionId: SessionId): URL;
}

const configuredTransports = new WeakSet<object>();

export const startRuntimeTransport = (configure: () => void | Promise<void>): Promise<void> => {
  try {
    return Promise.resolve(configure());
  } catch (error) {
    return Promise.reject(error);
  }
};

export const configureServerTransport = <SessionId>(
  runtime: RuntimeTransport<SessionId>,
  editMode: boolean,
) => {
  if (configuredTransports.has(runtime)) {
    return;
  }
  configuredTransports.add(runtime);
  const configure = (url: URL) => {
    url.searchParams.delete(RUNTIME_QUERY_KEY);
    if (editMode) {
      url.searchParams.set("kiosk", "true");
    }
    return url;
  };
  const getWsURL = runtime.getWsURL.bind(runtime);
  const getSseURL = runtime.getSseURL.bind(runtime);

  runtime.getWsURL = (sessionId) => configure(getWsURL(sessionId));
  runtime.getSseURL = (sessionId) => configure(getSseURL(sessionId));
};
