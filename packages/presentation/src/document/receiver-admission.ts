import type {
  ReceiverAdmittedMessage,
  ReceiverReadyMessage,
} from "@marimo-studio/protocol/preview-messages";

import { parsePreviewMessage } from "@marimo-studio/protocol/preview-messages";

import { isStudioParentMessage, postToStudioParent } from "./parent-bridge.ts";
import { studioOwned } from "./studio-ownership.ts";

export interface ReceiverAdmissionTarget {
  readonly lifecycleId: number;
  readonly runtime: string;
  readonly view: string;
  revision(): string;
}

export const waitForReceiverAdmission = (
  target: ReceiverAdmissionTarget,
  owned = studioOwned(),
  signal?: AbortSignal,
): Promise<ReceiverAdmittedMessage | undefined> => {
  if (!owned) {
    return Promise.resolve(undefined);
  }
  if (signal?.aborted) {
    return Promise.reject(signal.reason);
  }
  return new Promise((resolve, reject) => {
    function cleanup() {
      globalThis.removeEventListener("message", listener);
      signal?.removeEventListener("abort", retired);
    }
    function retired() {
      cleanup();
      reject(signal?.reason);
    }
    function listener(event: MessageEvent<unknown>) {
      if (!isStudioParentMessage(event)) {
        return;
      }
      const message = parsePreviewMessage(event.data);
      if (
        message?.type !== "marimo-studio:receiver-admitted" ||
        message.runtime !== target.runtime ||
        message.view !== target.view ||
        message.lifecycleId !== target.lifecycleId ||
        message.revision !== target.revision()
      ) {
        return;
      }
      cleanup();
      resolve(message);
    }
    globalThis.addEventListener("message", listener);
    signal?.addEventListener("abort", retired, { once: true });
    const ready: ReceiverReadyMessage = {
      type: "marimo-studio:receiver-ready",
      runtime: target.runtime,
      lifecycleId: target.lifecycleId,
      view: target.view,
      revision: target.revision(),
    };
    postToStudioParent(ready);
  });
};
