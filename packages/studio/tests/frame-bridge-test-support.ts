import {
  parseFrameBridgeMessage,
  type FrameBridgeMessage,
  type FrameControlUpdate,
  type ControlMetadata,
} from "@marimo-studio/protocol/frame-bridge";
import { vi } from "vite-plus/test";

export interface TestFrameIdentity {
  lifecycleId: number;
  revision: string;
  runtime: string;
  sessionId: string | null;
  view: string;
}

export interface TestFrameSource {
  postMessage: ReturnType<typeof vi.fn>;
}

type FrameAppliedResponse = Extract<
  FrameBridgeMessage,
  {
    type: "marimo-studio:frame-control-applied" | "marimo-studio:frame-query-applied";
  }
>;

export const dispatchFrameBridgeMessage = (
  source: TestFrameSource,
  data: FrameBridgeMessage,
): void => {
  const event = new MessageEvent("message", { data, origin: "null" });
  Object.defineProperty(event, "source", { value: source });
  globalThis.dispatchEvent(event);
};

export const createFrameBridgeSource = (
  responseError: (message: FrameBridgeMessage) => string | undefined = () => undefined,
): TestFrameSource => {
  const source: TestFrameSource = {
    postMessage: vi.fn((value: FrameBridgeMessage) => {
      const message = parseFrameBridgeMessage(value);
      if (
        message?.type !== "marimo-studio:frame-control-apply" &&
        message?.type !== "marimo-studio:frame-query-apply"
      ) {
        return;
      }
      const type =
        message.type === "marimo-studio:frame-control-apply"
          ? "marimo-studio:frame-control-applied"
          : "marimo-studio:frame-query-applied";
      const error = responseError(message);
      const response: FrameAppliedResponse = {
        type,
        generation: message.generation,
        lifecycleId: message.lifecycleId,
        revision: message.revision,
        runtime: message.runtime,
        sessionId: message.sessionId,
        view: message.view,
        requestId: message.requestId,
      };
      if (error !== undefined) {
        response.error = error;
      }
      queueMicrotask(() => dispatchFrameBridgeMessage(source, response));
    }),
  };
  return source;
};

export const installFrameBridge = (
  frame: HTMLIFrameElement,
  source: TestFrameSource,
  identity: TestFrameIdentity,
  controls: readonly FrameControlUpdate[] = [],
  controlMetadata: ControlMetadata = { cells: {} },
): void => {
  frame.dataset.previewFrame = "";
  frame.dataset.previewLifecycleId = String(identity.lifecycleId);
  if (!frame.isConnected) {
    document.body.append(frame);
  }
  Object.defineProperty(frame, "contentWindow", {
    configurable: true,
    value: source,
  });
  dispatchFrameBridgeMessage(source, {
    type: "marimo-studio:frame-bridge-ready",
    generation: "generation-test",
    controls: [...controls],
    controlMetadata,
    ...identity,
  });
};

export const sendFrameControlUpdate = (
  source: TestFrameSource,
  identity: TestFrameIdentity,
  update: FrameControlUpdate,
): void => {
  dispatchFrameBridgeMessage(source, {
    type: "marimo-studio:frame-control-update",
    generation: "generation-test",
    update,
    ...identity,
  });
};
