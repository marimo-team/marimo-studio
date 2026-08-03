export interface ViewTransitionHooks {
  prepare(view: string): Promise<boolean>;
  commit(view: string, created: boolean): void;
  cancel(): void;
}

/** Commits the latest requested view after its asynchronous source load. */
export class ViewTransition {
  private generation = 0;

  constructor(
    private current: string,
    private readonly hooks: ViewTransitionHooks,
  ) {}

  async select(view: string, created = false): Promise<boolean> {
    const generation = ++this.generation;
    if (view === this.current) {
      this.hooks.cancel();
      return true;
    }
    if (!(await this.hooks.prepare(view)) || generation !== this.generation) {
      return false;
    }
    this.current = view;
    this.hooks.commit(view, created);
    return true;
  }
}
