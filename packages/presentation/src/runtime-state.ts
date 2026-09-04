import type { JsonObject } from "@marimo-studio/protocol/json";

export { setRuntimeConnectionState } from "./rendered-view-observer.ts";

export interface RuntimeStateDescription {
  readonly fingerprint: string;
  readonly aliases: readonly string[];
  readonly inputs: JsonObject;
}

export interface RuntimeStateApi {
  inputs(): JsonObject;
  states(): readonly RuntimeStateDescription[];
  update(patch: JsonObject): Promise<void>;
}
