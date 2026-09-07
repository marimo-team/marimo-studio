export interface PreviewNavigationOwner {
  readonly generation: number;
}

export interface StagedPreviewView {
  ready: Promise<boolean>;
  commit?(): void;
  rollback(): Promise<void>;
}

export interface StagedNavigationQuery {
  ready: Promise<boolean>;
  rollback(): Promise<boolean>;
}

export class PreviewNavigation {
  private generation = 0;
  private current: PreviewNavigationOwner | undefined;

  get pending(): boolean {
    return this.current !== undefined;
  }

  owns(owner: PreviewNavigationOwner): boolean {
    return this.current === owner;
  }

  stage(
    prepareQuery?: (owner: PreviewNavigationOwner) => StagedNavigationQuery,
    stageView?: () => StagedPreviewView,
  ): StagedPreviewView {
    const transaction = { generation: ++this.generation };
    this.current = transaction;
    const query = prepareQuery?.(transaction);
    let preview: StagedPreviewView | undefined;
    let rollingBack = false;
    let rollback: Promise<void> | undefined;
    const ready = (async () => {
      if ((query && !(await query.ready)) || rollingBack || this.current !== transaction) {
        return false;
      }
      if (!stageView) {
        return true;
      }
      preview = stageView();
      if (rollingBack) {
        await preview.rollback();
        return false;
      }
      const prepared = await preview.ready;
      return !rollingBack && this.current === transaction && prepared;
    })();
    return {
      ready,
      commit: () => {
        if (this.current === transaction) {
          this.current = undefined;
        }
      },
      rollback: () => {
        rollingBack = true;
        rollback ??= (async () => {
          if (this.current !== transaction) {
            return;
          }
          const failures: unknown[] = [];
          try {
            try {
              await preview?.rollback();
            } catch (error) {
              failures.push(error);
            }
            try {
              if (!((await query?.rollback()) ?? true)) {
                failures.push(new Error("The previous notebook query could not be restored."));
              }
            } catch (error) {
              failures.push(error);
            }
          } finally {
            if (this.current === transaction) {
              this.current = undefined;
            }
          }
          if (failures.length === 1) {
            throw failures[0];
          }
          if (failures.length > 1) {
            throw new AggregateError(failures, "The previous view could not be restored.");
          }
        })();
        return rollback;
      },
    };
  }
}
