import type { StudioDiagnostic } from "./diagnostics.ts";

import { projectionHosts } from "./projections/host-runtime.ts";
import { collectStudioDiagnostics } from "./readiness-diagnostics.ts";
import { readiness } from "./readiness.ts";
import {
  getMountConfig,
  getRuntimeConfig,
  getRuntimeDiagnostics,
  getSupportUrl,
  hasRuntimeConfig,
} from "./runtime-config/index.ts";
import { serverRuntimeDataSchema } from "./runtime/server-config.ts";
import { viewStyleDiagnostic } from "./view-styles/runtime.ts";

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

const mountedRuntimeSession = (config?: ReturnType<typeof getRuntimeConfig>) => {
  const mount = getMountConfig();
  if (mount.runtime !== "server") {
    return undefined;
  }
  if (!mount.runtimeSessionId) {
    return undefined;
  }
  if (config) {
    const runtime =
      config.runtime.id === "server"
        ? serverRuntimeDataSchema.safeParse(config.runtime.data)
        : undefined;
    if (!runtime?.success || runtime.data.sessionId !== mount.runtimeSessionId) {
      throw new Error("The rendered session does not match its mount authority");
    }
  }
  return mount.runtimeSessionId;
};

export const renderedViewIdentity = (): RenderedViewIdentity => {
  if (hasRuntimeConfig()) {
    const config = getRuntimeConfig();
    return {
      runtime: config.runtime.id,
      view: config.view,
      revision: config.revision,
      runtimeInstance: config.runtime.instance,
      sessionId: mountedRuntimeSession(config),
    };
  }
  const mount = getMountConfig();
  return {
    runtime: mount.runtime,
    view: configuredView(),
    revision: mount.revision,
    sessionId: mountedRuntimeSession(),
  };
};

export const renderedViewDiagnostics = (): readonly StudioDiagnostic[] => {
  const snapshot = readiness.snapshot();
  const view = configuredView();
  const style = viewStyleDiagnostic();
  return [
    ...collectStudioDiagnostics({
      configured: hasRuntimeConfig() ? getRuntimeDiagnostics() : [],
      hosts: projectionHosts.hosts(),
      runtime: snapshot.runtimeDiagnostic,
      presentation: [
        ...(snapshot.presentationDiagnostic ? [snapshot.presentationDiagnostic] : []),
        ...(style
          ? [
              {
                ...style,
                scope: "presentation" as const,
                severity: "error" as const,
                view,
              },
            ]
          : []),
      ],
      view,
    }),
  ];
};
