// @deno-types="npm:@types/react@19.2.10"
import { useCallback, useEffect, useState } from "react";

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

export type MarimoValueElement<T = MarimoValue> = HTMLSpanElement & {
  marimoValue?: T;
};

/** Return a live notebook value and a ref for its explicit `mo-value` host. */
export const useMarimoValue = <T = MarimoValue>(selector: string) => {
  const [host, setHost] = useState<MarimoValueElement<T> | null>(null);
  const [value, setValue] = useState<T>();
  const [error, setError] = useState(false);
  const hostRef = useCallback((node: MarimoValueElement<T> | null) => {
    setHost(node);
  }, []);

  useEffect(() => {
    if (host === null) {
      return;
    }

    const sync = () => {
      setValue(host.marimoValue);
      setError(host.dataset.marimoError !== undefined);
    };
    const fail = () => setError(true);

    host.addEventListener("marimo-value-updated", sync);
    host.addEventListener("marimo-value-error", fail);
    sync();

    return () => {
      host.removeEventListener("marimo-value-updated", sync);
      host.removeEventListener("marimo-value-error", fail);
    };
  }, [host, selector]);

  return { error, hostRef, value };
};
