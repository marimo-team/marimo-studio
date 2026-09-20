import type { FrameBridgeMessage } from "@marimo-studio/protocol/frame-bridge";
import type {
  PresentationToStudioMessage,
  PresentationToWrapperMessage,
} from "@marimo-studio/protocol/preview-messages";

import { getMountConfig } from "../runtime-config/store.ts";

type StudioParentMessage =
  | FrameBridgeMessage
  | PresentationToStudioMessage
  | PresentationToWrapperMessage;

const studioOrigin = (): string => {
  try {
    return new URL(getMountConfig().supportUrl, globalThis.location.href).origin;
  } catch {
    return globalThis.location.origin;
  }
};

export const isStudioParentMessage = (event: MessageEvent<unknown>): boolean =>
  event.source === globalThis.parent && event.origin === studioOrigin();

export const postToStudioParent = (message: StudioParentMessage): void => {
  if (globalThis.parent !== globalThis.window) {
    globalThis.parent.postMessage(message, studioOrigin());
  }
};
