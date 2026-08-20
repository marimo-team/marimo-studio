import type {
  RuntimeControlPathStep,
  RuntimeControls,
} from "@marimo-studio/protocol/runtime-config";

export interface ControlUpdate {
  objectId: string;
  value: unknown;
}

export interface ControlEvent extends ControlUpdate {
  readonly origin: "input" | "registration";
}

export interface EndpointControlBinding {
  readonly input: string;
  readonly path: readonly RuntimeControlPathStep[];
}

export type EndpointControlBindings = Readonly<Record<string, EndpointControlBinding>>;

export interface ControlEndpoint {
  snapshot(): readonly ControlUpdate[];
  controlBindings?(): EndpointControlBindings | undefined;
  subscribeControlBindings?(listener: (bindings: EndpointControlBindings) => void): () => void;
  subscribeTopology?(listener: (objectId: string) => void): () => void;
  subscribe(listener: (update: ControlEvent) => void): () => void;
  apply(updates: readonly ControlUpdate[]): Promise<void>;
  applyLocal?(updates: readonly ControlUpdate[]): Promise<void>;
  dispose(): void;
}

export type ControlFrameConnector = (frame: HTMLIFrameElement) => ControlEndpoint | undefined;
export type ControlSource = "editor" | "preview";

export interface ControlSyncUpdate {
  readonly editor?: RuntimeControls;
  readonly preview?: RuntimeControls;
}

export interface ControlSync {
  invalidateControls(source?: ControlSource): void;
  isQuarantined(): boolean;
  quarantineVersion(): number;
  quarantinedSources(): ReadonlySet<ControlSource>;
  updateControls(controls?: ControlSyncUpdate): Promise<void>;
  dispose(): void;
}
