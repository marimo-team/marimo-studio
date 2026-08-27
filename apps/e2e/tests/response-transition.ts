export interface TransitionRequestIdentity {
  method(): string;
  url(): string;
}

interface TransitionOperation<Owner extends object> {
  readonly owner: Owner;
  readonly start: number;
  readonly startedAfterSeal: boolean;
}

export class ResponseTransitionWindow<
  Request extends TransitionRequestIdentity & object,
  Owner extends object,
> {
  private readonly operations = new Map<Request, TransitionOperation<Owner>>();
  private readonly failedOwners = new Map<Owner, number>();
  private readonly recoveredOwners = new Set<Owner>();
  private readonly origin: string;
  private acceptingFailures = true;
  private failures = 0;
  private invalidRecovery = false;
  private isRecovered = false;
  private overflow = false;
  private postSealFailure = false;

  constructor(
    origin: string,
    private readonly method: string,
    private readonly path: RegExp,
    private readonly failureStatus: number,
    private readonly failureError: string,
    private readonly successStatus: number,
    private readonly failureLimit = 64,
  ) {
    this.origin = new URL(origin).origin;
    if (!method || !failureError) {
      throw new Error("Response transitions require a method and failure code.");
    }
    if (!Number.isSafeInteger(failureLimit) || failureLimit < 1) {
      throw new RangeError("Response transitions require a positive failure limit.");
    }
  }

  recordStart(request: Request, owner: Owner, start: number): boolean {
    if (this.isRecovered || !this.matches(request)) {
      return false;
    }
    if (!this.operations.has(request)) {
      this.operations.set(request, {
        owner,
        start,
        startedAfterSeal: !this.acceptingFailures,
      });
    }
    return true;
  }

  recordResponse(request: Request, status: number, errorCode: string | undefined): boolean {
    const operation = this.operations.get(request);
    if (operation === undefined) {
      return false;
    }
    this.operations.delete(request);
    if (status === this.failureStatus && errorCode === this.failureError) {
      if (operation.startedAfterSeal) {
        this.postSealFailure = true;
      }
      this.failures += 1;
      if (this.failures > this.failureLimit) {
        this.overflow = true;
        return true;
      }
      this.failedOwners.set(
        operation.owner,
        Math.max(this.failedOwners.get(operation.owner) ?? 0, operation.start),
      );
      return true;
    }
    if (status === this.successStatus && errorCode === undefined) {
      if (!this.acceptingFailures && operation.startedAfterSeal) {
        const failedStart = this.failedOwners.get(operation.owner);
        if (failedStart !== undefined && operation.start > failedStart) {
          this.recoveredOwners.add(operation.owner);
        }
      }
      return true;
    }
    return false;
  }

  recordTerminal(request: Request): void {
    this.operations.delete(request);
  }

  seal(): void {
    this.acceptingFailures = false;
  }

  readyToRecover(): boolean {
    return (
      !this.acceptingFailures &&
      !this.invalidRecovery &&
      !this.isRecovered &&
      this.operations.size === 0 &&
      !this.overflow &&
      !this.postSealFailure &&
      [...this.failedOwners].every(([owner]) => this.recoveredOwners.has(owner))
    );
  }

  recover(): boolean {
    if (!this.readyToRecover()) {
      this.invalidRecovery = true;
      return false;
    }
    this.isRecovered = true;
    return true;
  }

  diagnostics(): string[] {
    const messages: string[] = [];
    if (this.operations.size > 0) {
      messages.push(`response transition retained ${this.operations.size} pending request(s)`);
    }
    if (this.overflow) {
      messages.push(`response transition exceeded ${this.failureLimit} failure response(s)`);
    }
    if (this.postSealFailure) {
      messages.push("response transition observed a failure after repair started");
    }
    const missingOwners = [...this.failedOwners].filter(
      ([owner]) => !this.recoveredOwners.has(owner),
    ).length;
    if (missingOwners > 0) {
      messages.push(`response transition retained ${missingOwners} owner(s) without recovery`);
    }
    if (this.invalidRecovery) {
      messages.push("response transition recovered before its exact terminal state");
    } else if (!this.isRecovered && !this.acceptingFailures) {
      messages.push("response transition had no observed recovery");
    }
    return messages;
  }

  private matches(request: TransitionRequestIdentity): boolean {
    const url = new URL(request.url());
    this.path.lastIndex = 0;
    return (
      request.method() === this.method && url.origin === this.origin && this.path.test(url.pathname)
    );
  }
}
