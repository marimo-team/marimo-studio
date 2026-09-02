interface ReceiverRefreshCallbacks {
  readonly ready: () => void;
  readonly unready: () => void;
  readonly viewReady: () => void;
}

export class ReceiverRefreshHandshake {
  private pending = false;

  constructor(private readonly callbacks: ReceiverRefreshCallbacks) {}

  get active(): boolean {
    return this.pending;
  }

  begin(): void {
    if (this.pending) {
      return;
    }
    this.pending = true;
    this.callbacks.unready();
  }

  complete(): void {
    if (!this.pending) {
      return;
    }
    this.pending = false;
    this.callbacks.ready();
    this.callbacks.viewReady();
  }

  release(): void {
    this.pending = false;
  }
}
