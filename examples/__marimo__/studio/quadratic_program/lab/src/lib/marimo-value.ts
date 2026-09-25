export type MarimoJsonValue =
  | null
  | boolean
  | number
  | string
  | MarimoJsonValue[]
  | { [key: string]: MarimoJsonValue };

export const MARIMO_DATA_SOURCE = Symbol.for("marimo-studio.data-source");

export interface MarimoDataSource {
  readonly codec: string;
  readonly fingerprint: string;
  readonly bytes: Uint8Array;
}

export interface MarimoColumn<T = unknown> extends Iterable<T> {
  readonly length: number;
  readonly nullCount: number;
  get(index: number): T | null | undefined;
  toArray(): ArrayLike<T> & Iterable<T>;
}

export interface MarimoTable<
  Row extends object = Record<string, unknown>,
> extends Iterable<Row> {
  readonly [MARIMO_DATA_SOURCE]?: MarimoDataSource;
  readonly numRows: number;
  readonly numCols: number;
  readonly names: readonly (keyof Row & string)[];
  readonly schema: {
    readonly fields: readonly {
      readonly name: string;
      readonly type: {
        readonly typeId: number;
        readonly [key: string]: unknown;
      };
      readonly nullable: boolean;
    }[];
  };
  get(index: number): Row | null;
  getChild<Name extends keyof Row & string>(
    name: Name,
  ): MarimoColumn<Row[Name]> | undefined;
  select<Name extends keyof Row & string>(
    names: readonly Name[],
  ): MarimoTable<Pick<Row, Name>>;
  toColumns(): {
    readonly [Name in keyof Row]: ArrayLike<Row[Name]> & Iterable<Row[Name]>;
  };
  toArray(): Row[];
}

export type MarimoValue = MarimoJsonValue | MarimoTable;

export const isMarimoTable = (value: unknown): value is MarimoTable =>
  Object.prototype.toString.call(value) === "[object Table]";

export const getMarimoDataSource = (
  value: unknown,
): MarimoDataSource | undefined => {
  if (
    (typeof value !== "object" && typeof value !== "function") ||
    value === null
  ) {
    return undefined;
  }
  return (value as Record<symbol, MarimoDataSource | undefined>)[
    MARIMO_DATA_SOURCE
  ];
};

export type MarimoValueElement<T = MarimoValue> = HTMLElement & {
  marimoValue?: T;
};

export type MarimoValueOptions<T = MarimoValue> = {
  selector: string;
  onValue: (value: T) => void;
  onError?: () => void;
};

/** Subscribe an explicit `mo-value` host to current values and later updates. */
export const observeMarimoValue = <T = MarimoValue>(
  node: HTMLElement,
  options: MarimoValueOptions<T>,
) => {
  let current = options;
  const host = node as MarimoValueElement<T>;

  const sync = () => {
    if (host.marimoValue !== undefined) {
      current.onValue(host.marimoValue);
    }
  };
  const fail = () => current.onError?.();

  host.addEventListener("marimo-value-updated", sync);
  host.addEventListener("marimo-value-error", fail);
  // A host that failed before this action mounted keeps its error on the host.
  if (host.dataset.marimoError === undefined) {
    sync();
  } else {
    fail();
  }

  return {
    update(next: MarimoValueOptions<T>) {
      current = next;
    },
    destroy() {
      host.removeEventListener("marimo-value-updated", sync);
      host.removeEventListener("marimo-value-error", fail);
    },
  };
};
