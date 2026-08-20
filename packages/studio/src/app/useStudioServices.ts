import type { ActiveViewRequest } from "@marimo-studio/protocol/development-events";
import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import { type RefCallback, useCallback, useEffect, useMemo, useState } from "react";

import type { ControlFrameConnector } from "../features/preview/control-types.ts";
import type { StudioServices } from "./services.ts";

import { errorMessage } from "../shared/errors.ts";
import { createStudioServices } from "./services.ts";

interface StudioServiceBinding extends StudioServices {
  editorFrame: HTMLIFrameElement;
  frameRef: (frameId: string) => RefCallback<HTMLIFrameElement>;
}

interface StartupFailure {
  services: StudioServices;
  error: Error;
}

export const useStudioServices = (
  bootstrap: StudioBootstrap,
  editorFrame: HTMLIFrameElement,
  initialActivation?: ActiveViewRequest,
  connectControlFrame?: ControlFrameConnector,
): StudioServiceBinding => {
  const services = useMemo(
    () => createStudioServices(bootstrap, connectControlFrame, initialActivation),
    [bootstrap, connectControlFrame, initialActivation],
  );
  const [startupFailure, setStartupFailure] = useState<StartupFailure | null>(null);
  const [previewFrames] = useState(() => new Map<string, HTMLIFrameElement>());
  const frameCallbacks = useMemo(
    () =>
      new Map(
        services.previewFrameIds.map((frameId) => [
          frameId,
          (element: HTMLIFrameElement | null) => {
            if (element) {
              previewFrames.set(frameId, element);
            } else {
              previewFrames.delete(frameId);
            }
          },
        ]),
      ),
    [previewFrames, services.previewFrameIds],
  );
  const frameRef = useCallback(
    (frameId: string) => {
      const callback = frameCallbacks.get(frameId);
      if (!callback) {
        throw new Error(`Missing preview frame callback for ${frameId}`);
      }
      return callback;
    },
    [frameCallbacks],
  );

  useEffect(() => {
    let active = true;
    void services.start(editorFrame, previewFrames).catch((cause: unknown) => {
      if (active) {
        setStartupFailure({ services, error: new Error(errorMessage(cause)) });
      }
    });

    const protectPendingSource = (event: BeforeUnloadEvent) => {
      if (services.source.hasPendingChanges) {
        event.preventDefault();
      }
    };
    const stopArranging = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        services.layout.stopArranging();
      }
    };
    const releasePage = (event: PageTransitionEvent) => {
      if (!event.persisted) {
        void services.close().catch(() => undefined);
      }
    };
    globalThis.addEventListener("beforeunload", protectPendingSource);
    globalThis.addEventListener("keydown", stopArranging);
    globalThis.addEventListener("pagehide", releasePage);

    return () => {
      active = false;
      globalThis.removeEventListener("beforeunload", protectPendingSource);
      globalThis.removeEventListener("keydown", stopArranging);
      globalThis.removeEventListener("pagehide", releasePage);
      void services.close().catch(() => undefined);
    };
  }, [editorFrame, previewFrames, services]);

  if (startupFailure?.services === services) {
    throw startupFailure.error;
  }

  return { ...services, editorFrame, frameRef };
};
