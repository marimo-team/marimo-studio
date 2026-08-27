import type { ControlEndpoint } from "@marimo-studio/marimo-frontend/control-endpoint";

import { connectCurrentControlEndpoint } from "@marimo-studio/marimo-frontend/control-endpoint";
import {
  frameControlUpdateSchema,
  parseFrameBridgeMessage,
  type FrameBridgeMessage,
  type FrameControlUpdate,
} from "@marimo-studio/protocol/frame-bridge";
import { publicNotebookQuery } from "@marimo-studio/protocol/query";

import { errorMessage } from "../errors.ts";
import { getRuntimeConfig, subscribeRuntimeConfig } from "../runtime-config/index.ts";
import { updateConfiguredRuntimeQuery } from "../runtime/coordinator.ts";
import { nextBrowserOperationId } from "./browser-operation-id.ts";
import { activeDocumentLifecycleId } from "./document-lifecycle-id.ts";
import { isStudioParentMessage, postToStudioParent } from "./parent-bridge.ts";
import { studioOwned } from "./studio-ownership.ts";

const acceptedUpdate = <Input>(value: Input): FrameControlUpdate | undefined => {
  const parsed = frameControlUpdateSchema.safeParse(value);
  return parsed.success ? parsed.data : undefined;
};

export interface FrameRuntimeBridgeDependencies {
  connectControlEndpoint(): ControlEndpoint | undefined;
  updateRuntimeQuery(query: string): Promise<void>;
}

const frameRuntimeBridgeDependencies: FrameRuntimeBridgeDependencies = {
  connectControlEndpoint: connectCurrentControlEndpoint,
  updateRuntimeQuery: updateConfiguredRuntimeQuery,
};

interface FrameIdentity {
  lifecycleId: number;
  revision: string;
  runtime: string;
  sessionId: string | null;
  view: string;
}

type FrameAppliedMessage = Extract<
  FrameBridgeMessage,
  {
    type: "marimo-studio:frame-control-applied" | "marimo-studio:frame-query-applied";
  }
>;

const currentIdentity = (sessionId: string | null): FrameIdentity => {
  const config = getRuntimeConfig();
  return {
    lifecycleId: activeDocumentLifecycleId(),
    revision: config.revision,
    runtime: config.runtime.id,
    sessionId,
    view: config.view,
  };
};

const sameIdentity = (message: FrameIdentity, identity: FrameIdentity): boolean =>
  message.lifecycleId === identity.lifecycleId &&
  message.revision === identity.revision &&
  message.runtime === identity.runtime &&
  message.sessionId === identity.sessionId &&
  message.view === identity.view;

const result = (
  type: "marimo-studio:frame-control-applied" | "marimo-studio:frame-query-applied",
  generation: string,
  requestId: string,
  identity: FrameIdentity,
  cause?: unknown,
): FrameBridgeMessage => {
  const message: FrameAppliedMessage = {
    type,
    generation,
    requestId,
    ...identity,
  };
  if (cause !== undefined) {
    message.error = errorMessage(cause).slice(0, 1_024);
  }
  return message;
};

const commitQuery = (query: string, hash?: string): void => {
  const target = new URL(globalThis.location.href);
  for (const key of new URLSearchParams(publicNotebookQuery(target.search)).keys()) {
    target.searchParams.delete(key);
  }
  for (const [key, value] of new URLSearchParams(publicNotebookQuery(query))) {
    target.searchParams.append(key, value);
  }
  if (hash !== undefined) {
    target.hash = hash;
  }
  globalThis.history.replaceState(
    globalThis.history.state,
    "",
    `${target.pathname}${target.search}${target.hash}`,
  );
};

export const startFrameRuntimeBridge = (
  sessionId: string | null,
  dependencies: FrameRuntimeBridgeDependencies = frameRuntimeBridgeDependencies,
): (() => void) => {
  if (globalThis.parent === globalThis.window || !studioOwned()) {
    return () => {};
  }
  const generation = nextBrowserOperationId();
  let disposed = false;
  let endpoint: ControlEndpoint | undefined;
  let stopControls = () => {};
  const post = (message: FrameBridgeMessage) => {
    if (!disposed) {
      postToStudioParent(message);
    }
  };
  const owns = (identity: FrameIdentity): boolean =>
    !disposed && sameIdentity(identity, currentIdentity(sessionId));
  const connectEndpoint = (): ControlEndpoint | undefined => {
    if (endpoint) {
      return endpoint;
    }
    endpoint = dependencies.connectControlEndpoint();
    if (!endpoint) {
      return undefined;
    }
    stopControls = endpoint.subscribe((update) => {
      const accepted = acceptedUpdate(update);
      if (accepted) {
        post({
          type: "marimo-studio:frame-control-update",
          generation,
          update: accepted,
          ...currentIdentity(sessionId),
        });
      }
    });
    return endpoint;
  };
  const applyControls = async (
    message: Extract<FrameBridgeMessage, { type: "marimo-studio:frame-control-apply" }>,
    identity: FrameIdentity,
  ): Promise<void> => {
    await Promise.resolve();
    if (!owns(identity)) {
      return;
    }
    const currentEndpoint = connectEndpoint();
    if (!currentEndpoint) {
      post(
        result(
          "marimo-studio:frame-control-applied",
          generation,
          message.requestId,
          identity,
          new Error("The presentation control endpoint is unavailable"),
        ),
      );
      return;
    }
    try {
      await currentEndpoint.apply(message.updates);
      if (owns(identity)) {
        post(
          result("marimo-studio:frame-control-applied", generation, message.requestId, identity),
        );
      }
    } catch (cause) {
      if (owns(identity)) {
        post(
          result(
            "marimo-studio:frame-control-applied",
            generation,
            message.requestId,
            identity,
            cause,
          ),
        );
      }
    }
  };
  const applyQuery = async (
    message: Extract<FrameBridgeMessage, { type: "marimo-studio:frame-query-apply" }>,
    identity: FrameIdentity,
  ): Promise<void> => {
    await Promise.resolve();
    if (!owns(identity)) {
      return;
    }
    try {
      await dependencies.updateRuntimeQuery(message.query);
      if (!owns(identity)) {
        return;
      }
      commitQuery(message.query, message.hash);
      post(result("marimo-studio:frame-query-applied", generation, message.requestId, identity));
    } catch (cause) {
      if (owns(identity)) {
        post(
          result(
            "marimo-studio:frame-query-applied",
            generation,
            message.requestId,
            identity,
            cause,
          ),
        );
      }
    }
  };
  const postReady = () => {
    const controls = (connectEndpoint()?.snapshot() ?? [])
      .map(acceptedUpdate)
      .filter((update): update is FrameControlUpdate => update !== undefined);
    post({
      type: "marimo-studio:frame-bridge-ready",
      generation,
      controls,
      ...currentIdentity(sessionId),
    });
  };
  const stopConfig = subscribeRuntimeConfig(postReady);

  const receive = (event: MessageEvent<unknown>) => {
    if (!isStudioParentMessage(event)) {
      return;
    }
    const message = parseFrameBridgeMessage(event.data);
    const identity = currentIdentity(sessionId);
    if (!message || message.generation !== generation || !sameIdentity(message, identity)) {
      return;
    }
    if (message.type === "marimo-studio:frame-resize") {
      globalThis.dispatchEvent(new Event("resize"));
      return;
    }
    if (message.type === "marimo-studio:frame-control-apply") {
      void applyControls(message, identity);
      return;
    }
    if (message.type === "marimo-studio:frame-query-apply") {
      void applyQuery(message, identity);
    }
  };
  globalThis.addEventListener("message", receive);
  postReady();
  return () => {
    if (disposed) {
      return;
    }
    disposed = true;
    globalThis.removeEventListener("message", receive);
    stopConfig();
    stopControls();
    endpoint?.dispose();
  };
};
