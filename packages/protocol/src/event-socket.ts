import { z } from "zod";

import { jsonCodec, jsonValueSchema, type JsonValue } from "./json.ts";

/**
 * One Studio development event. The server sends each event as a JSON text
 * frame on a WebSocket: `{"event": "change", "data": {"kind": "views"}}`.
 */
export interface StudioEvent {
  readonly event: string;
  readonly data: JsonValue;
}

const studioEventCodec = jsonCodec(
  z.object({ event: z.string().min(1), data: jsonValueSchema }).strip(),
);

export const parseStudioEvent = (frame: string): StudioEvent | undefined => {
  const result = studioEventCodec.safeDecode(frame);
  return result.success ? result.data : undefined;
};

/**
 * Studio accepts a rejected event socket and closes it with `4000 + status`
 * of the HTTP response that the route returned for the handshake.
 */
export const EVENT_SOCKET_REJECTED = 4000;
/** The event URL was issued by an earlier server process. */
export const EVENT_SOCKET_RETIRED = EVENT_SOCKET_REJECTED + 204;
/** The server refuses the capability that the event URL carries. */
export const EVENT_SOCKET_FORBIDDEN = EVENT_SOCKET_REJECTED + 403;

/** Return the WebSocket address of an HTTP event route. */
export const eventSocketUrl = (url: string, base?: string): string => {
  const target = new URL(url, base);
  target.protocol = target.protocol === "https:" ? "wss:" : "ws:";
  return target.href;
};
