import {
  prepareCellHosts,
  registerMarimoCellElement,
  syncPreservedCellHosts,
} from "../cells/host.ts";
import {
  prepareOutputHosts,
  registerMarimoOutputElement,
  syncPreservedOutputHosts,
} from "../outputs/host.ts";
import { startValueBindings, stopValueBindings } from "../values/hosts.ts";
import { subscribeProjectionChanges } from "./changes.ts";

interface ProjectionHostAdapter {
  readonly selector: string;
  register(): void;
  connect(): void;
  disconnect(): void;
  prepare(root: ParentNode): void;
  preserve(source: ParentNode, live: Document): void;
}

const passive = () => {};

const adapters: readonly ProjectionHostAdapter[] = [
  {
    selector: "marimo-cell",
    register: registerMarimoCellElement,
    connect: passive,
    disconnect: passive,
    prepare: prepareCellHosts,
    preserve: syncPreservedCellHosts,
  },
  {
    selector: "marimo-output",
    register: registerMarimoOutputElement,
    connect: passive,
    disconnect: passive,
    prepare: prepareOutputHosts,
    preserve: syncPreservedOutputHosts,
  },
  {
    selector: "[mo-value]",
    register: passive,
    connect: startValueBindings,
    disconnect: stopValueBindings,
    prepare: passive,
    preserve: passive,
  },
];

export class ProjectionHostRuntime {
  private registered = false;
  private connected = false;

  register(): void {
    if (this.registered) {
      return;
    }
    this.registered = true;
    adapters.forEach((adapter) => adapter.register());
    this.prepare(document);
  }

  connect(): void {
    if (this.connected) {
      return;
    }
    this.register();
    this.connected = true;
    adapters.forEach((adapter) => adapter.connect());
  }

  disconnect(): void {
    if (!this.connected) {
      return;
    }
    this.connected = false;
    adapters.forEach((adapter) => adapter.disconnect());
  }

  prepare(root: ParentNode): void {
    adapters.forEach((adapter) => adapter.prepare(root));
  }

  preserve(source: ParentNode, live: Document): void {
    adapters.forEach((adapter) => adapter.preserve(source, live));
  }

  subscribe(listener: () => void): () => void {
    return subscribeProjectionChanges(listener);
  }

  states(root: ParentNode = document): string[] {
    return adapters.flatMap((adapter) =>
      Array.from(
        root.querySelectorAll<HTMLElement>(adapter.selector),
        (host) => host.dataset.state ?? "connecting",
      ),
    );
  }
}

export const projectionHosts = new ProjectionHostRuntime();
