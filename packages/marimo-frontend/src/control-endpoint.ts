import {
  connectControlEndpoint as createControlEndpoint,
  type ControlEndpoint,
  type SendControlValues,
  type UIElementRegistry,
} from "./control-endpoint-core.ts";
import { MarimoValueReadyEvent } from "./upstream/controls.ts";

type MarimoWindow = Window & {
  _marimo_private_UIElementRegistry?: UIElementRegistry;
  _marimo_private_RuntimeState?: {
    _sendComponentValues?: SendControlValues;
  };
};

const eventObjectId = (event: Event): string | undefined => {
  if (!MarimoValueReadyEvent.is(event)) {
    return undefined;
  }
  return typeof event.detail.objectId === "string" ? event.detail.objectId : undefined;
};

export type { ControlEndpoint, ControlUpdate } from "./control-endpoint-core.ts";

export const connectControlEndpoint = (frame: HTMLIFrameElement): ControlEndpoint | undefined => {
  const browser = frame.contentWindow as MarimoWindow | null;
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
