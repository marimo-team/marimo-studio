import { getSessionId } from "@marimo-studio/marimo-frontend/runtime";

import { errorMessage } from "../errors.ts";
import { renderedViewIdentity } from "../rendered-view-state.ts";
import {
  fetchRuntimeConfigForRevision,
  getRuntimeConfig,
  RuntimeConfigRequestError,
} from "../runtime-config/index.ts";
import { updateConfiguredRuntime } from "../runtime/coordinator.ts";
import {
  PresentationRevisionController,
  type RevisionOperation,
  type SessionReplayPort,
} from "./revision-controller.ts";
import { DocumentRevisionAdapter } from "./revision-document.ts";
import { BrowserSessionReplay } from "./session-preservation.ts";

export const presentationSessionId = getSessionId();

const browserSessionReplay = new BrowserSessionReplay();
const sessionReplay: SessionReplayPort = {
  prepare: (config) => browserSessionReplay.prepare(config),
  preservedUrl: (target) => browserSessionReplay.preservedUrl(getRuntimeConfig(), target),
  finish: () => browserSessionReplay.finish(),
  remember: (sessionId) => browserSessionReplay.remember(getRuntimeConfig(), sessionId),
};

const classifyFailure = (error: unknown, _operation: RevisionOperation) => ({
  state: "error" as const,
  diagnostic: {
    scope: "presentation" as const,
    code:
      error instanceof RuntimeConfigRequestError ? error.code : "presentation-transition-failed",
    severity: "error" as const,
    message: errorMessage(error),
    hint:
      error instanceof RuntimeConfigRequestError && error.hint
        ? error.hint
        : "Fix the view source, then try the navigation again.",
    view: renderedViewIdentity().view,
  },
});

export const presentationRevisions = new PresentationRevisionController(
  new DocumentRevisionAdapter(presentationSessionId),
  presentationSessionId,
  {
    applyRuntime: () => updateConfiguredRuntime(getRuntimeConfig()),
    loadRevision: (config, previewSessionId, signal) =>
      fetchRuntimeConfigForRevision(
        config.supportUrl,
        config.revision,
        signal,
        config.runtime.id,
        previewSessionId,
      ),
    reloadDocument: (url) => globalThis.location.assign(url),
    reloadRuntime: () => globalThis.location.reload(),
    classifyFailure,
  },
  sessionReplay,
);
