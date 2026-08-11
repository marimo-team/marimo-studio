import type { SessionId } from "@marimo-studio/marimo-frontend/session-bootstrap";

import type { RuntimeConfig } from "../runtime-config/index.ts";

interface SessionReplayPreflight {
  pending(): boolean;
  preflight(config: RuntimeConfig): boolean;
}

export const bootstrapPresentationSession = async ({
  bootstrap,
  loadConfig,
  replay,
  requiresSessionForConfig,
}: {
  bootstrap: (preflight: () => void | Promise<void>) => Promise<SessionId>;
  loadConfig: (sessionId?: SessionId) => Promise<RuntimeConfig>;
  replay: SessionReplayPreflight;
  requiresSessionForConfig: boolean;
}): Promise<{ config: RuntimeConfig; replaying: boolean; sessionId: SessionId }> => {
  let config: RuntimeConfig | undefined;
  let replaying = false;
  const sessionId = await bootstrap(async () => {
    if (requiresSessionForConfig) {
      return;
    }
    config = await loadConfig();
    replaying = replay.preflight(config);
  });
  if (!config || replaying) {
    config = await loadConfig(sessionId);
  }
  return {
    config,
    replaying: replaying || replay.pending(),
    sessionId,
  };
};
