import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import { type RefCallback, useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ControlFrameConnector } from "../preview/control-sync.ts";
import type { StudioServices } from "./services.ts";

import { errorMessage } from "../errors.ts";
import { createStudioServices } from "./services.ts";

interface StudioServiceBinding extends StudioServices {
  editorFrame: HTMLIFrameElement | null;
  editorRef: RefCallback<HTMLIFrameElement>;
  frameRef: (runtime: string) => RefCallback<HTMLIFrameElement>;
}

interface StartupFailure {
  services: StudioServices;
  error: Error;
}

export const useStudioServices = (
  bootstrap: StudioBootstrap,
  connectControlFrame?: ControlFrameConnector,
): StudioServiceBinding => {
  const services = useMemo(
    () => createStudioServices(bootstrap, connectControlFrame),
    [bootstrap, connectControlFrame],
  );
  const editor = useRef<HTMLIFrameElement | null>(null);
  const [editorFrame, setEditorFrame] = useState<HTMLIFrameElement | null>(null);
  const [startupFailure, setStartupFailure] = useState<StartupFailure | null>(null);
  const [previewFrames] = useState(() => new Map<string, HTMLIFrameElement>());
  const frameCallbacks = useMemo(
    () =>
      new Map(
        services.runtimeIds.map((runtime) => [
          runtime,
          (element: HTMLIFrameElement | null) => {
            if (element) {
              previewFrames.set(runtime, element);
            } else {
              previewFrames.delete(runtime);
            }
          },
        ]),
      ),
    [previewFrames, services.runtimeIds],
  );
  const editorRef = useCallback((element: HTMLIFrameElement | null) => {
    editor.current = element;
    setEditorFrame(element);
  }, []);
  const frameRef = useCallback(
    (runtime: string) => {
      const callback = frameCallbacks.get(runtime);
      if (!callback) {
        throw new Error(`Missing preview frame callback for ${runtime}`);
      }
      return callback;
    },
    [frameCallbacks],
  );

  useEffect(() => {
    const editorFrame = editor.current;
    if (!editorFrame) {
      setStartupFailure({
        services,
        error: new Error("Studio notebook frame did not mount"),
      });
      return;
    }
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
    globalThis.addEventListener("beforeunload", protectPendingSource);
    globalThis.addEventListener("keydown", stopArranging);

    return () => {
      active = false;
      globalThis.removeEventListener("beforeunload", protectPendingSource);
      globalThis.removeEventListener("keydown", stopArranging);
      services.dispose();
    };
  }, [previewFrames, services]);

  if (startupFailure?.services === services) {
    throw startupFailure.error;
  }

  return { ...services, editorFrame, editorRef, frameRef };
};
