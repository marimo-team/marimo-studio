import type { ShellChangeKind } from "@marimo-studio/protocol/development-events";

export interface ShellTarget {
  documentUrl: string;
  supportUrl: string;
}

export interface VersionedShellTarget extends ShellTarget {
  revision: string;
}

export const sameShellPresentation = (
  current: VersionedShellTarget,
  next: VersionedShellTarget,
): boolean => {
  return (
    current.documentUrl === next.documentUrl &&
    current.supportUrl === next.supportUrl &&
    current.revision === next.revision
  );
};

const changePriority: Record<ShellChangeKind, number> = {
  css: 0,
  views: 1,
  runtime: 2,
  html: 3,
};

const queuedShellChange = (
  current: ShellChangeKind | undefined,
  incoming: ShellChangeKind,
): ShellChangeKind => {
  if (current === undefined || changePriority[incoming] > changePriority[current]) {
    return incoming;
  }
  return current;
};

export class ShellChangeQueue {
  #change: ShellChangeKind | undefined;

  push(kind: ShellChangeKind): void {
    this.#change = queuedShellChange(this.#change, kind);
  }

  take(): ShellChangeKind | undefined {
    const change = this.#change;
    this.#change = undefined;
    return change;
  }
}

export class RefreshRetrySchedule {
  #attempt = 0;

  constructor(private readonly delays: readonly number[] = [1_000, 2_000, 5_000, 10_000, 30_000]) {
    if (delays.length === 0) {
      throw new Error("Refresh retry schedule requires at least one delay");
    }
  }

  next(): number {
    const delay = this.delays[Math.min(this.#attempt, this.delays.length - 1)];
    this.#attempt += 1;
    return delay;
  }

  reset(): void {
    this.#attempt = 0;
  }
}

export class BaselineReconciler {
  #configured: boolean;
  #pending = false;

  constructor(configured: boolean) {
    this.#configured = configured;
  }

  ready(): boolean {
    if (!this.#configured) {
      this.#pending = true;
      return false;
    }
    return true;
  }

  configure(): boolean {
    this.#configured = true;
    if (!this.#pending) {
      return false;
    }
    this.#pending = false;
    return true;
  }
}

export class ShellRefreshState {
  #failedTarget: ShellTarget | undefined;

  get pending(): boolean {
    return this.#failedTarget !== undefined;
  }

  get failedTarget(): ShellTarget | undefined {
    return this.#failedTarget && { ...this.#failedTarget };
  }

  rememberFailure(target: ShellTarget): void {
    this.#failedTarget = target;
  }

  supersede(): void {
    this.#failedTarget = undefined;
  }

  complete(target: ShellTarget): void {
    if (
      this.#failedTarget?.documentUrl === target.documentUrl &&
      this.#failedTarget.supportUrl === target.supportUrl
    ) {
      this.#failedTarget = undefined;
    }
  }

  targetForChange(kind: ShellChangeKind, fallback: ShellTarget): ShellTarget | undefined {
    if (kind === "css") {
      return this.#failedTarget;
    }
    if (kind === "views" && !this.#failedTarget) {
      return undefined;
    }
    return this.#failedTarget ?? fallback;
  }
}
