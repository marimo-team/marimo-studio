import {
  connectControlEndpoint as createControlEndpoint,
  type ControlEndpoint,
  type ControlRegistry,
  type SendControlValues,
} from "./control-endpoint-core.ts";
import { MarimoValueReadyEvent } from "./upstream/controls.ts";

declare global {
  interface Window {
    _marimo_private_UIElementRegistry?: ControlRegistry;
    _marimo_private_RuntimeState?: {
      _sendComponentValues?: SendControlValues;
    };
  }
}

const eventObjectId = (event: Event): string | undefined => {
  if (!MarimoValueReadyEvent.is(event)) {
    return undefined;
  }
  return event.detail.objectId;
};

export type { ControlEndpoint, ControlUpdate } from "./control-endpoint-core.ts";

export const connectControlEndpoint = (frame: HTMLIFrameElement): ControlEndpoint | undefined => {
  const browser = frame.contentWindow;
  const registry = browser?._marimo_private_UIElementRegistry;
  const sendControlValues = browser?._marimo_private_RuntimeState?._sendComponentValues;
  if (!browser || !registry || !sendControlValues) {
    return undefined;
  }

  return createControlEndpoint(
    browser.document,
    registry,
    {
      type: MarimoValueReadyEvent.TYPE,
      objectId: eventObjectId,
    },
    sendControlValues,
  );
};
