import EventEmitter from "events";

type EventModule = { EventEmitter: typeof EventEmitter };
type BrowserModuleScope = typeof globalThis & {
  require?: (specifier: string) => EventModule;
};

const scope: BrowserModuleScope = globalThis;

// Deno bundles the CommonJS queue used by React PDF with one Node event-module
// lookup. Route that lookup to React PDF's browser events dependency.
if (scope.require === undefined) {
  scope.require = (specifier) => {
    if (specifier === "events" || specifier === "node:events") {
      return { EventEmitter };
    }
    throw new Error(`Browser module is unavailable: ${specifier}`);
  };
}
