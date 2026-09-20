import { startRegisteredNotebookProcess } from "./registered-notebook-process.mjs";
import { captureProcessOutput } from "./server-process.mjs";

export const startRoutedNotebookProcess = ({ endpoint, forward = {}, ...options }) => {
  const serverUrl = endpoint.origin;
  const registration = startRegisteredNotebookProcess({ ...options, port: null });
  const output = captureProcessOutput(registration.child, forward);
  let port = null;
  let closing = false;
  let release;
  const beginClose = () => {
    closing = true;
  };
  const releaseRoute = () => {
    closing = true;
    release?.();
  };
  registration.child.once("exit", releaseRoute);
  const ready = Promise.all([registration.ready, registration.bound]).then(([, boundPort]) => {
    port = boundPort;
    if (closing) throw new Error("Notebook service closed before binding its route");
    release = endpoint.bindBackend(port);
  });
  void ready.catch(() => undefined);
  return {
    ...registration,
    get port() {
      return port;
    },
    serverUrl,
    output,
    ready,
    beginClose,
    releaseRoute,
  };
};
