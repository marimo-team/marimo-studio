import {
  connectControlEndpoint as createControlEndpoint,
  type ControlBindings,
  type ControlEndpoint,
  type ControlRegistry,
  type SendControlValues,
  type SubscribeControlBindings,
} from "./control-endpoint-core.ts";
import { MarimoValueReadyEvent } from "./upstream/controls.ts";

declare global {
  interface Window {
    _marimo_private_UIElementRegistry?: ControlRegistry;
    _marimo_private_RuntimeState?: {
      _sendComponentValues?: SendControlValues;
      _controlBindings?: ControlBindings;
      _subscribeControlBindings?: SubscribeControlBindings;
    };
  }
}

const eventObjectId = (event: Event): string | undefined => {
  if (!MarimoValueReadyEvent.is(event)) {
    return undefined;
  }
  return event.detail.objectId;
};

export type {
  ControlBinding,
  ControlBindings,
  ControlBindingsListener,
  ControlEvent,
  ControlEndpoint,
  ControlPathStep,
  ControlTopologyListener,
  SubscribeControlBindings,
  ControlUpdate,
} from "./control-endpoint-core.ts";

const connectWindowControlEndpoint = (
  browser: Window | null,
  target: EventTarget,
): ControlEndpoint | undefined => {
  const registry = browser?._marimo_private_UIElementRegistry;
  const sendControlValues = browser?._marimo_private_RuntimeState?._sendComponentValues;
  if (!browser || !registry || !sendControlValues) {
    return undefined;
  }

  return createControlEndpoint(
    target,
    registry,
    {
      type: MarimoValueReadyEvent.TYPE,
      objectId: eventObjectId,
    },
    sendControlValues,
    () => browser._marimo_private_RuntimeState?._controlBindings,
    (listener) =>
      browser._marimo_private_RuntimeState?._subscribeControlBindings?.(listener) ?? (() => {}),
  );
};

export const connectCurrentControlEndpoint = (): ControlEndpoint | undefined =>
  connectWindowControlEndpoint(globalThis.window, globalThis.document);

export const connectControlEndpoint = (frame: HTMLIFrameElement): ControlEndpoint | undefined => {
  try {
    const browser = frame.contentWindow;
    return browser ? connectWindowControlEndpoint(browser, browser.document) : undefined;
  } catch {
    return undefined;
  }
};
