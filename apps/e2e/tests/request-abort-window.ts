import type { BrowserRequestIdentity } from "./request-identity.ts";

export class ExactRequestAbortWindow<Request extends BrowserRequestIdentity & object> {
  private readonly activeRequests = new Set<Request>();
  private readonly aborted = new Set<Request>();
  private readonly responseStatuses = new Map<Request, number>();
  private readonly origin: string;
  private accepting = true;
  private extraAborts = 0;
  private invalidRecovery = false;
  private isRecovered = false;

  constructor(
    private readonly method: string,
    origin: string,
    private readonly path: RegExp,
    private readonly expectedCount = 1,
    private readonly required = true,
    private readonly expectedStatus?: number,
  ) {
    if (!method) {
      throw new Error("Exact request abort windows require an HTTP method.");
    }
    if (!Number.isSafeInteger(expectedCount) || expectedCount < 1) {
      throw new RangeError("Exact request abort windows require a positive count.");
    }
    if (
      expectedStatus !== undefined &&
      (!Number.isSafeInteger(expectedStatus) || expectedStatus < 100 || expectedStatus > 599)
    ) {
      throw new RangeError("Exact request abort windows require a valid HTTP status.");
    }
    this.origin = new URL(origin).origin;
  }

  recordStart(request: Request): boolean {
    if (!this.accepting || this.isRecovered || !this.matches(request)) {
      return false;
    }
    if (this.activeRequests.has(request) || this.aborted.has(request)) {
      return true;
    }
    this.activeRequests.add(request);
    return true;
  }

  recordAbort(request: Request, errorText: string): boolean {
    if (
      this.isRecovered ||
      errorText !== "net::ERR_ABORTED" ||
      !this.activeRequests.has(request) ||
      this.aborted.has(request)
    ) {
      return false;
    }
    this.activeRequests.delete(request);
    if (this.aborted.size >= this.expectedCount) {
      this.extraAborts += 1;
    } else {
      this.aborted.add(request);
    }
    return true;
  }

  recordActive(request: Request, status: number | undefined): boolean {
    if (!this.recordStart(request)) {
      return false;
    }
    if (status !== undefined) {
      this.recordResponse(request, status);
    }
    return true;
  }

  recordResponse(request: Request, status: number): boolean {
    if (!this.activeRequests.has(request) && !this.aborted.has(request)) {
      return false;
    }
    this.responseStatuses.set(request, status);
    return true;
  }

  recordTerminal(request: Request): boolean {
    if (!this.activeRequests.delete(request)) {
      return false;
    }
    this.responseStatuses.delete(request);
    return true;
  }

  seal(): void {
    this.accepting = false;
  }

  recover(): boolean {
    this.accepting = false;
    if (!this.readyToRecover()) {
      this.invalidRecovery = true;
      return false;
    }
    this.isRecovered = true;
    return true;
  }

  readyToRecover(): boolean {
    const exactAborts = this.required
      ? this.aborted.size === this.expectedCount
      : this.aborted.size <= this.expectedCount;
    return (
      !this.accepting &&
      !this.invalidRecovery &&
      !this.isRecovered &&
      exactAborts &&
      this.activeRequests.size === 0 &&
      !this.hasUnexpectedStatus() &&
      this.extraAborts === 0
    );
  }

  diagnostics(): string[] {
    const messages: string[] = [];
    if (this.required && this.aborted.size !== this.expectedCount) {
      messages.push(
        `expected ${this.expectedCount} exact ${this.method} request abort(s) for ${this.path}, saw ${this.aborted.size}`,
      );
    }
    if (this.extraAborts > 0) {
      messages.push(
        `exact ${this.method} request window for ${this.path} observed ${this.extraAborts} extra abort(s)`,
      );
    }
    if (this.activeRequests.size > 0) {
      messages.push(
        `exact ${this.method} request window for ${this.path} retained ${this.activeRequests.size} active request(s)`,
      );
    }
    if (this.hasUnexpectedStatus()) {
      messages.push(
        `exact ${this.method} request window for ${this.path} did not observe HTTP ${this.expectedStatus} for every abort`,
      );
    }
    if (this.invalidRecovery) {
      messages.push(`exact ${this.method} request window for ${this.path} recovered early`);
    } else if (this.aborted.size > 0 && !this.isRecovered) {
      messages.push(`exact ${this.method} request abort for ${this.path} had no observed recovery`);
    }
    return messages;
  }

  private matches(request: BrowserRequestIdentity): boolean {
    const url = new URL(request.url());
    this.path.lastIndex = 0;
    return (
      request.method() === this.method && url.origin === this.origin && this.path.test(url.pathname)
    );
  }

  private hasUnexpectedStatus(): boolean {
    return (
      this.expectedStatus !== undefined &&
      [...this.aborted].some(
        (request) => this.responseStatuses.get(request) !== this.expectedStatus,
      )
    );
  }
}
