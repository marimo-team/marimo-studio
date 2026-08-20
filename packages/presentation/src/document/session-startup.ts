import type { RuntimeConfig } from "../runtime-config/index.ts";

interface SessionReplayPreflight {
  pending(): boolean;
  preflight(config: RuntimeConfig): boolean;
}

export class PresentationDocumentRetiredError extends Error {
  constructor() {
    super("The presentation document was retired");
    this.name = "PresentationDocumentRetiredError";
  }
}

const throwIfRetired = (signal?: AbortSignal): void => {
  if (signal?.aborted) {
    throw signal.reason;
  }
};

const settleOwned = async <T>(operation: Promise<T>, signal?: AbortSignal): Promise<T> => {
  try {
    const value = await operation;
    throwIfRetired(signal);
    return value;
  } catch (cause) {
    if (signal?.aborted) {
      throw signal.reason;
    }
    throw cause;
  }
};

export interface PresentationSessionBootstrapResult {
  config: RuntimeConfig;
  replaying: boolean;
  sessionId?: string;
}

export const bootstrapSessionlessPresentation = async (
  loadConfig: () => Promise<RuntimeConfig>,
): Promise<PresentationSessionBootstrapResult> => ({
  config: await loadConfig(),
  replaying: false,
});

export const bootstrapPresentationSession = async ({
  bootstrap,
  loadConfig,
  replay,
  requiresSessionForConfig,
  signal,
}: {
  bootstrap: (preflight: () => void | Promise<void>) => Promise<string>;
  loadConfig: (sessionId?: string) => Promise<RuntimeConfig>;
  replay: SessionReplayPreflight;
  requiresSessionForConfig: boolean;
  signal?: AbortSignal;
}): Promise<PresentationSessionBootstrapResult> => {
  throwIfRetired(signal);
  let config: RuntimeConfig | undefined;
  let replaying = false;
  const sessionId = await settleOwned(
    bootstrap(async () => {
      throwIfRetired(signal);
      if (requiresSessionForConfig) {
        return;
      }
      config = await settleOwned(loadConfig(), signal);
      replaying = replay.preflight(config);
      throwIfRetired(signal);
    }),
    signal,
  );
  if (
    !config ||
    replaying ||
    (config.presentationSessionId !== undefined && config.runtime.id === "server")
  ) {
    config = await settleOwned(loadConfig(sessionId), signal);
  }
  return {
    config,
    replaying: replaying || replay.pending(),
    sessionId,
  };
};
