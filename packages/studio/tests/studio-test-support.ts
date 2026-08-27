import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

export const studioBootstrap: StudioBootstrap = {
  schema: 1,
  notebook: { name: "analysis.py" },
  selectedView: "dashboard",
  views: ["dashboard", "report"],
  runtimes: [
    { id: "server", label: "Server" },
    { id: "wasm", label: "WebAssembly" },
  ],
  defaultRuntime: "server",
  clientId: "browser-client-1234",
  serverInstance: "server-instance",
  urls: {
    editor: "/?file=analysis.py",
    agent: "/_marimo-studio",
    events: "/_marimo-studio/dev/events",
    query: "/_marimo-studio/query",
    studioPrefix: "/studio/",
    viewPrefix: "/",
    viewSupportPrefix: "/_marimo-studio/views",
    views: "/_marimo-studio/views",
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
