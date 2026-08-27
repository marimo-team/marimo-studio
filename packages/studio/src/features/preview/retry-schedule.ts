export class RetrySchedule {
  #attempt = 0;

  constructor(private readonly delays: readonly number[] = [1_000, 2_000, 5_000, 10_000, 30_000]) {
    if (delays.length === 0) {
      throw new Error("Retry schedule requires at least one delay");
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
