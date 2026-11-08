import { artifactPublicPathSchema } from "@marimo-studio/protocol/source-documents";

import { readiness } from "../readiness.ts";
import { configuredView } from "../rendered-view-state.ts";
import { initialDocumentBaseUrl } from "./base.ts";

interface WorkerFailure {
  readonly url: string;
  readonly message: string;
}

declare global {
  // The worker fallback fills this before the runtime module loads.
  var __MARIMO_STUDIO_WORKER_ERRORS__: { push(failure: WorkerFailure): void } | undefined;
}

// View scripts load from the initial base, and inline module scripts report
// the page URL captured before Studio rewrites the query.
const viewBase = initialDocumentBaseUrl;
const pageUrl = document.URL.split("#")[0];

const viewSource = (url: string): string | undefined => {
  const address = url.split(/[?#]/)[0];
  if (url.split("#")[0] === pageUrl) {
    return "inline script";
  }
  if (!address.startsWith(viewBase)) {
    return undefined;
  }
  // Studio's runtime and notebook files share the base under reserved roots.
  const path = decodedPath(address.slice(viewBase.length));
  return path !== undefined && artifactPublicPathSchema.safeParse(path).success ? path : undefined;
};

// A malformed escape leaves the error unattributed.
const decodedPath = (value: string): string | undefined => {
  try {
    return decodeURIComponent(value);
  } catch {
    return undefined;
  }
};

const describe = (cause: unknown): string =>
  cause instanceof Error ? `${cause.name}: ${cause.message}` : String(cause);

const stackLocation = (cause: unknown): [string, number, number] | undefined => {
  const match =
    cause instanceof Error ? cause.stack?.match(/(\w+:\/\/[^\s()]+?):(\d+):(\d+)/) : null;
  return match ? [match[1], Number(match[2]), Number(match[3])] : undefined;
};

const report = (url: string, line: number, column: number, cause: unknown): void => {
  const source = viewSource(url);
  if (source === undefined) {
    return;
  }
  readiness.fail({
    code: "view-script-error",
    severity: "error",
    message: `${source}:${line}:${column}: ${describe(cause)}`,
    hint: "Fix the view source, build the view, then reload the page. The browser console has the stack.",
    view: configuredView(),
    scope: "presentation",
  });
};

// Browser messages can quote URLs, and Studio's URLs carry the capability.
const withoutUrls = (message: string): string =>
  message.replace(/https?:\/\/[^\s'"]+/g, (url) => viewSource(url) ?? "(worker URL)");

const workerName = (url: string): string =>
  /^(?:blob|data):/.test(url) ? "inline worker" : `worker ${viewSource(url) ?? "script"}`;

// Worker libraries often recover from their own failures, so the view keeps
// running.
const reportWorkerFailure = ({ url, message }: WorkerFailure): void => {
  readiness.warn({
    code: "view-worker-error",
    severity: "warning",
    message: `${workerName(url)}: ${withoutUrls(message) || "failed to start"}`,
    hint: "Check the worker's script path and startup code. A classic worker that throws while loading reports a load failure.",
    view: configuredView(),
    scope: "presentation",
  });
};

const drainWorkerFailures = (): void => {
  const buffered = globalThis.__MARIMO_STUDIO_WORKER_ERRORS__;
  if (Array.isArray(buffered)) {
    globalThis.__MARIMO_STUDIO_WORKER_ERRORS__ = { push: reportWorkerFailure };
    buffered.forEach(reportWorkerFailure);
  }
};

/** Fail the page on the first uncaught error from the view's own scripts. */
export const watchViewScriptErrors = (): (() => void) => {
  drainWorkerFailures();
  // Browser warnings such as ResizeObserver loops arrive without an error value.
  const onError = (event: ErrorEvent) => {
    if (event.error != null) {
      report(event.filename, event.lineno, event.colno, event.error);
    }
  };
  const onRejection = (event: PromiseRejectionEvent) => {
    const frame = stackLocation(event.reason);
    if (frame) {
      report(...frame, event.reason);
    }
  };
  globalThis.addEventListener("error", onError);
  globalThis.addEventListener("unhandledrejection", onRejection);
  return () => {
    globalThis.removeEventListener("error", onError);
    globalThis.removeEventListener("unhandledrejection", onRejection);
  };
};
