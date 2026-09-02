import type { Table } from "@uwdata/flechette";

export { tableFromIPC } from "@uwdata/flechette";
export type { Table } from "@uwdata/flechette";

export const MARIMO_DATA_SOURCE: unique symbol = Symbol.for("marimo-studio.data-source");

export interface MarimoDataSource {
  readonly codec: string;
  readonly fingerprint: string;
  readonly bytes: Uint8Array<ArrayBuffer>;
}

export interface MarimoDataSourceCarrier {
  readonly [MARIMO_DATA_SOURCE]: MarimoDataSource;
}

export type MarimoArrowTable = Table & MarimoDataSourceCarrier;

export const attachMarimoDataSource = (
  value: Table,
  source: MarimoDataSource,
): MarimoArrowTable => {
  Object.defineProperty(value, MARIMO_DATA_SOURCE, {
    configurable: false,
    enumerable: false,
    value: source,
    writable: false,
  });
  // SAFETY: The property definition above establishes the carrier contract.
  return value as MarimoArrowTable;
};

const isMarimoDataSourceCarrier = <Input>(value: Input): value is Input & MarimoDataSourceCarrier =>
  value !== null && Object(value) === value && Object.hasOwn(Object(value), MARIMO_DATA_SOURCE);

export const getMarimoDataSource = <Input>(value: Input): MarimoDataSource | undefined =>
  isMarimoDataSourceCarrier(value) ? value[MARIMO_DATA_SOURCE] : undefined;
