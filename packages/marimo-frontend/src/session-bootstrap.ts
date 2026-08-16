import type { SessionId } from "./upstream/session.ts";

import { createSessionBootstrap } from "./session-bootstrap-core.ts";

export type { SessionId };

export const isSessionId = (value: string | null | undefined): value is SessionId =>
  value != null && /^s_[\da-z]{6}$/.test(value);

const session = createSessionBootstrap(async () => {
  const source = await import("./upstream/session.ts");
  return source.getSessionId();
});

export const bootstrapSession = session.bootstrap;
export const currentSessionId = session.current;
