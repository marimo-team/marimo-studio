interface ReceiverRefreshCallbacks {
  readonly ready: () => void;
  readonly unready: () => void;
  readonly viewReady: () => void;
}

export class ReceiverRefreshHandshake {
  private state: "idle" | "pending" | "failed" = "idle";

  constructor(private readonly callbacks: ReceiverRefreshCallbacks) {}

  /** Whether the receiver withholds lifecycle readiness. */
  get active(): boolean {
    return this.state !== "idle";
  }

  begin(): void {
    if (this.state === "pending") {
      return;
    }
    this.state = "pending";
    this.callbacks.unready();
  }

  complete(): void {
    if (this.state !== "pending") {
      return;
    }
    this.state = "idle";
    this.callbacks.ready();
    this.callbacks.viewReady();
  }

  /**
   * End a refresh that failed. The receiver stays unready until the next
   * `begin` announces a retry.
   */
  fail(): void {
    if (this.state === "pending") {
      this.state = "failed";
    }
  }

  release(): void {
    this.state = "idle";
  }
}
