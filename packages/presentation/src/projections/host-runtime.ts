import {
  getCellHosts,
  prepareCellHosts,
  registerMarimoCellElement,
  syncPreservedCellHosts,
} from "../cells/host.ts";
import {
  getOutputHosts,
  prepareOutputHosts,
  registerMarimoOutputElement,
  syncPreservedOutputHosts,
} from "../outputs/host.ts";
import {
  getValueHosts,
  prepareValueHosts,
  startValueHosts,
  stopValueHosts,
  syncPreservedValueHosts,
} from "../values/hosts.ts";
import { isArtifactProjectionHost } from "./artifact-host.ts";
import { subscribeProjectionChanges } from "./changes.ts";
import { hostsInDocumentOrder } from "./host-order.ts";

interface ProjectionHostAdapter {
  readonly selector: string;
  register(): void;
  connect(): void;
  disconnect(): void;
  prepare(root: ParentNode): void;
  preserve(source: ParentNode, live: Document): void;
}

export interface StagedHostPreservation {
  commit(): void;
  rollback(): void;
  finalize(): void;
  discard(): void;
}

interface PreservedHost {
  source: HTMLElement;
  live: HTMLElement;
  attributes: readonly [string, string][];
  target: Comment;
  rollback?: Comment;
  moved: boolean;
}

const restoreAttributes = (host: PreservedHost): void => {
  Array.from(host.live.attributes).forEach((attribute) =>
    host.live.removeAttribute(attribute.name),
  );
  host.attributes.forEach(([name, value]) => host.live.setAttribute(name, value));
};

type MovableParent = Node & {
  moveBefore?: (node: Node, child: Node | null) => void;
};

const moveBefore = (node: Node, marker: Comment): void => {
  const parent: MovableParent | null = marker.parentNode;
  if (!parent) {
    throw new Error("Preserved host marker is detached");
  }
  if (parent.moveBefore) {
    parent.moveBefore(node, marker);
  } else {
    parent.insertBefore(node, marker);
  }
};

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
    connect: startValueHosts,
    disconnect: stopValueHosts,
    prepare: prepareValueHosts,
    preserve: syncPreservedValueHosts,
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

  stagePreservation(source: ParentNode, live: Document): StagedHostPreservation {
    const hosts: PreservedHost[] = [];
    for (const adapter of adapters) {
      source
        .querySelectorAll<HTMLElement>(`${adapter.selector}[data-hx-preserve][id]`)
        .forEach((candidate) => {
          if (!isArtifactProjectionHost(candidate)) {
            return;
          }
          const current = live.getElementById(candidate.id);
          if (current?.localName !== candidate.localName || current === candidate) {
            return;
          }
          hosts.push({
            source: candidate,
            live: current,
            attributes: Array.from(current.attributes, (attribute) => [
              attribute.name,
              attribute.value,
            ]),
            target: document.createComment(`preserve ${candidate.id}`),
            moved: false,
          });
        });
    }
    try {
      this.preserve(source, live);
      hosts.forEach((host) => host.source.replaceWith(host.target));
    } catch (error) {
      hosts.forEach((host) => {
        if (host.target.parentNode) {
          host.target.replaceWith(host.source);
        }
      });
      hosts.forEach(restoreAttributes);
      throw error;
    }
    let committed = false;
    let finalized = false;
    const rollback = () => {
      if (finalized) {
        return;
      }
      [...hosts].reverse().forEach((host) => {
        if (host.moved && host.rollback?.parentNode) {
          moveBefore(host.live, host.rollback);
          host.moved = false;
        }
        host.rollback?.remove();
        host.rollback = undefined;
        if (host.target.parentNode) {
          host.target.replaceWith(host.source);
        }
        restoreAttributes(host);
      });
      committed = false;
    };
    return {
      commit: () => {
        if (committed || finalized) {
          return;
        }
        try {
          hosts.forEach((host) => {
            host.rollback = document.createComment(`restore ${host.live.id}`);
            host.live.before(host.rollback);
            moveBefore(host.live, host.target);
            host.moved = true;
          });
          committed = true;
        } catch (error) {
          rollback();
          throw error;
        }
      },
      rollback,
      finalize: () => {
        if (!committed || finalized) {
          return;
        }
        finalized = true;
        hosts.forEach((host) => {
          host.rollback?.remove();
          host.rollback = undefined;
          host.target.remove();
        });
      },
      discard: rollback,
    };
  }

  subscribe(listener: () => void): () => void {
    return subscribeProjectionChanges(listener);
  }

  states(root: ParentNode = document): string[] {
    return this.hosts().flatMap((host) =>
      root === document || root.contains(host) ? [host.dataset.state ?? "connecting"] : [],
    );
  }

  hosts(): readonly HTMLElement[] {
    return hostsInDocumentOrder([...getCellHosts(), ...getOutputHosts(), ...getValueHosts()]);
  }
}

export const projectionHosts = new ProjectionHostRuntime();
