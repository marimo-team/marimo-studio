import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

export const studioBootstrap: StudioBootstrap = {
  schema: 1,
  notebook: { name: "analysis.py" },
  defaultView: "dashboard",
  selectedView: "dashboard",
  views: ["dashboard", "report"],
  runtimes: [
    { id: "server", label: "Python" },
    { id: "wasm", label: "Browser" },
  ],
  defaultRuntime: "server",
  trustedServerRuntime: false,
  clientId: "browser-client-1234",
  serverInstance: "server-instance",
  urls: {
    editor: "http://localhost:3000/?file=analysis.py",
    agent: "http://localhost:3000/_marimo-studio",
    events: "http://localhost:3000/_marimo-studio/dev/events",
    query: "http://localhost:3000/_marimo-studio/query",
    studioPrefix: "http://localhost:3000/studio/",
    viewPrefix: "http://localhost:3000/",
    viewSupportPrefix: "http://localhost:3000/_marimo-studio/views",
    views: "http://localhost:3000/_marimo-studio/views",
  },
  workspaceId: "workspace",
  serverToken: "token",
};

export const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

export const studioFrames = (): Map<string, HTMLIFrameElement> =>
  new Map(studioBootstrap.runtimes.map(({ id }) => [id, document.createElement("iframe")]));
