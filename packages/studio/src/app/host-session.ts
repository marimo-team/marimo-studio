import {
  parseHostSessionConfig,
  type HostSessionConfig,
  parseHostSessionRecord,
  type HostSessionRecord,
} from "@marimo-studio/protocol/host-session";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";

type SessionStorage = Pick<Storage, "getItem" | "setItem">;
const unavailableSessionStorage: SessionStorage = {
  getItem: () => null,
  setItem: () => undefined,
};

export const resolveHostSessionStorage = (read: () => SessionStorage): SessionStorage => {
  try {
    return read();
  } catch {
    return unavailableSessionStorage;
  }
};

export const readHostSessionConfig = (
  root: Pick<Document, "querySelector"> = document,
): HostSessionConfig => {
  const source = root.querySelector<HTMLScriptElement>("#marimo-studio-host-session")?.textContent;
  if (!source) {
    throw new Error("Studio document is missing its host session config");
  }
  return parseHostSessionConfig(jsonValueSchema.parse(JSON.parse(source)));
};

const configuredRecord = (config: HostSessionConfig): HostSessionRecord => ({
  capability: config.capability,
  schema: 1,
  session: config.session,
});

const storedRecord = (
  config: HostSessionConfig,
  storage: SessionStorage,
): HostSessionRecord | undefined => {
  try {
    return parseHostSessionRecord(
      jsonValueSchema.parse(JSON.parse(storage.getItem(config.key) ?? "null")),
    );
  } catch {
    return undefined;
  }
};

const writeRecord = (
  config: HostSessionConfig,
  record: HostSessionRecord,
  storage: SessionStorage,
): void => {
  try {
    storage.setItem(config.key, JSON.stringify(record));
  } catch {
    // Browsers can deny session storage without blocking notebook navigation.
  }
};

export const hostSessionHandoffUrl = (
  config: HostSessionConfig,
  source: string,
  storage: SessionStorage,
): URL => {
  const retained = config.transition === "reset" ? undefined : storedRecord(config, storage);
  const record = retained ?? configuredRecord(config);
  writeRecord(config, record, storage);

  const target = new URL(source);
  target.searchParams.set("session_id", record.session);
  if (config.transition === "complete") {
    target.searchParams.delete(config.resume);
    target.searchParams.delete(config.handoff);
  } else if (config.transition === "studio" && retained) {
    target.searchParams.set(config.resume, "1");
    target.searchParams.delete(config.handoff);
  } else {
    target.searchParams.delete(config.resume);
    target.searchParams.set(config.handoff, record.capability);
  }
  return target;
};

export const studioHostUrl = (
  config: HostSessionConfig,
  source: string,
  storage: SessionStorage,
): URL => {
  writeRecord(config, configuredRecord(config), storage);
  const target = new URL(source);
  target.searchParams.delete("session_id");
  target.searchParams.delete(config.resume);
  target.searchParams.delete(config.handoff);
  return target;
};

export const handoffHostSession = (config: HostSessionConfig): void => {
  const storage = resolveHostSessionStorage(() => globalThis.sessionStorage);
  globalThis.location.replace(hostSessionHandoffUrl(config, globalThis.location.href, storage));
};

export const initializeStudioHostSession = (config: HostSessionConfig): void => {
  const storage = resolveHostSessionStorage(() => globalThis.sessionStorage);
  const target = studioHostUrl(config, globalThis.location.href, storage);
  globalThis.history.replaceState(globalThis.history.state, "", target);
};
