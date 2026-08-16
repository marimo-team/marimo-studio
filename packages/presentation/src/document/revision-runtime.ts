import type { SessionId } from "@marimo-studio/marimo-frontend/session-bootstrap";

import type { BrowserSessionReplay } from "./session-preservation.ts";

import { errorMessage } from "../errors.ts";
import { renderedViewIdentity } from "../rendered-view-state.ts";
import { getRuntimeConfig, RuntimeConfigRequestError } from "../runtime-config/index.ts";
import { updateConfiguredRuntime } from "../runtime/coordinator.ts";
import {
  PresentationRevisionController,
  type RevisionOperation,
  type SessionReplayPort,
} from "./revision-controller.ts";
import { DocumentRevisionAdapter } from "./revision-document.ts";

const classifyFailure = (cause: unknown, _operation: RevisionOperation) => ({
  state: "error" as const,
  diagnostic: {
    scope: "presentation" as const,
    code:
      cause instanceof RuntimeConfigRequestError ? cause.code : "presentation-transition-failed",
    severity: "error" as const,
    message: errorMessage(cause),
    hint:
      cause instanceof RuntimeConfigRequestError && cause.hint
        ? cause.hint
        : "Fix the view source, then try the navigation again.",
    view: renderedViewIdentity().view,
  },
});

let activeSessionId: SessionId | undefined;
let activeController: PresentationRevisionController | undefined;
let resolveController: (controller: PresentationRevisionController) => void;
const controllerReady = new Promise<PresentationRevisionController>((resolve) => {
  resolveController = resolve;
});

export const createPresentationRevisions = (
  sessionId: SessionId,
  browserSessionReplay: BrowserSessionReplay,
): PresentationRevisionController => {
  if (activeController) {
    if (activeSessionId !== sessionId) {
      throw new Error("Presentation revisions are already bound to another session");
    }
    return activeController;
  }
  const sessionReplay: SessionReplayPort = {
    preservedUrl: (target) => browserSessionReplay.preservedUrl(getRuntimeConfig(), target),
    remember: (currentSessionId) =>
      browserSessionReplay.remember(getRuntimeConfig(), currentSessionId),
  };
  activeSessionId = sessionId;
  activeController = new PresentationRevisionController(
    new DocumentRevisionAdapter(sessionId),
    sessionId,
    {
      applyRuntime: () => updateConfiguredRuntime(getRuntimeConfig()),
      reloadDocument: (url) => globalThis.location.assign(url),
      reloadRuntime: () => globalThis.location.reload(),
      classifyFailure,
    },
    sessionReplay,
  );
  resolveController(activeController);
  return activeController;
};

export const waitForPresentationRevisions = async (): Promise<PresentationRevisionController> =>
  activeController ?? controllerReady;
