import type { StudioDiagnostic } from "./diagnostics.ts";

import { collectStudioDiagnostics } from "./readiness-diagnostics.ts";
import { readiness } from "./readiness.ts";
import {
  getMountConfig,
  getRuntimeConfig,
  getRuntimeDiagnostics,
  getSupportUrl,
  hasRuntimeConfig,
  requestedRuntimeId,
} from "./runtime-config/index.ts";

export interface RenderedViewIdentity {
  readonly runtime: string;
  readonly view: string;
  readonly revision: string;
  readonly runtimeInstance?: string;
  readonly sessionId?: string;
}

const configuredView = (): string => {
  if (hasRuntimeConfig()) {
    return getRuntimeConfig().view;
  }
  try {
    return decodeURIComponent(
      new URL(getSupportUrl(), globalThis.location.origin).pathname
        .split("/")
        .filter(Boolean)
        .at(-1) ?? "",
    );
  } catch {
    return "";
  }
};

export const renderedViewIdentity = (): RenderedViewIdentity => {
  if (hasRuntimeConfig()) {
    const config = getRuntimeConfig();
    return {
      runtime: config.runtime.id,
      view: config.view,
      revision: config.revision,
      runtimeInstance: config.runtime.instance,
      sessionId: config.editorSessionId || globalThis.__MARIMO_STUDIO_SESSION_ID__,
    };
  }
  const mount = getMountConfig();
  return {
    runtime: requestedRuntimeId(mount.runtime),
    view: configuredView(),
    revision: mount.revision,
    sessionId: globalThis.__MARIMO_STUDIO_SESSION_ID__,
  };
};

export const renderedViewDiagnostics = (): readonly StudioDiagnostic[] => {
  const snapshot = readiness.snapshot();
  return collectStudioDiagnostics({
    configured: hasRuntimeConfig() ? getRuntimeDiagnostics() : [],
    runtime: snapshot.runtimeDiagnostic,
    presentation: snapshot.presentationDiagnostic,
    view: configuredView(),
  });
};

declare global {
  var __MARIMO_STUDIO_SESSION_ID__: string | undefined;
}
