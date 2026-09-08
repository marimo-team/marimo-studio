import {
  parseHostSessionConfig,
  type HostSessionConfig,
} from "@marimo-studio/protocol/host-session";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";

export const readHostSessionConfig = (
  root: Pick<Document, "querySelector"> = document,
): HostSessionConfig => {
  const source = root.querySelector<HTMLScriptElement>("#marimo-studio-host-session")?.textContent;
  if (!source) {
    throw new Error("Studio document is missing its host session config");
  }
  return parseHostSessionConfig(jsonValueSchema.parse(JSON.parse(source)));
};

export const hostSessionHandoffUrl = (config: HostSessionConfig, source: string): URL => {
  const target = new URL(source);
  target.searchParams.set("session_id", config.session);
  if (config.transition === "complete") {
    target.searchParams.delete(config.resume);
    target.searchParams.delete(config.handoff);
  } else {
    target.searchParams.delete(config.resume);
    target.searchParams.set(config.handoff, config.capability);
  }
  return target;
};

export const studioHostUrl = (config: HostSessionConfig, source: string): URL => {
  const target = new URL(source);
  target.searchParams.delete("session_id");
  target.searchParams.delete(config.resume);
  target.searchParams.delete(config.handoff);
  return target;
};

export const handoffHostSession = (config: HostSessionConfig): void => {
  globalThis.location.replace(hostSessionHandoffUrl(config, globalThis.location.href));
};

export const initializeStudioHostSession = (config: HostSessionConfig): void => {
  const target = studioHostUrl(config, globalThis.location.href);
  globalThis.history.replaceState(globalThis.history.state, "", target);
};
