export interface PresentationTarget {
  documentUrl: string;
  supportUrl: string;
}

export interface VersionedPresentationTarget extends PresentationTarget {
  revision: string;
}

export const samePresentationRevision = (
  current: VersionedPresentationTarget,
  next: VersionedPresentationTarget,
): boolean => current.revision === next.revision;

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
    }
    return false;
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

export class StaleBindingRefresh {
  #revision: string | undefined;

  request(revision: string): boolean {
    if (this.#revision === revision) {
      return false;
    }
    this.#revision = revision;
    return true;
  }

  needsRetry(currentRevision: string): boolean {
    if (this.#revision === undefined) {
      return false;
    }
    if (this.#revision === currentRevision) {
      return true;
    }
    this.#revision = undefined;
    return false;
  }

  clear(): void {
    this.#revision = undefined;
  }
}

export class PresentationRefreshState {
  #failedTarget: PresentationTarget | undefined;

  get failedTarget(): PresentationTarget | undefined {
    return this.#failedTarget && { ...this.#failedTarget };
  }

  rememberFailure(target: PresentationTarget): void {
    this.#failedTarget = target;
  }

  supersede(): void {
    this.#failedTarget = undefined;
  }

  complete(target: PresentationTarget): void {
    if (
      this.#failedTarget?.documentUrl === target.documentUrl &&
      this.#failedTarget.supportUrl === target.supportUrl
    ) {
      this.#failedTarget = undefined;
    }
  }
}
