export type ValuePhase =
  | "connecting"
  | "loading"
  | "stale"
  | "ready"
  | "error";

export interface ValueReadError {
  code: string;
  message: string;
  hint?: string;
}

export interface ValueState {
  phase: ValuePhase;
  error?: ValueReadError;
}

export class ValueStates {
  readonly #states = new Map<string, ValueState>();

  connected(selector: string, cached: boolean): ValueState {
    return this.#states.get(selector) ??
      { phase: cached ? "ready" : "connecting" };
  }

  pending(selector: string, cached: boolean): ValueState {
    const state: ValueState = {
      phase: cached ? "stale" : "loading",
    };
    this.#states.set(selector, state);
    return state;
  }

  failed(selector: string, error: ValueReadError): ValueState {
    const state: ValueState = { phase: "error", error };
    this.#states.set(selector, state);
    return state;
  }

  resolved(selector: string): ValueState {
    const state: ValueState = { phase: "ready" };
    this.#states.set(selector, state);
    return state;
  }

  clear(selector: string): void {
    this.#states.delete(selector);
  }
}
