import type { CellBindingConfig } from "../runtime-config/index.ts";

export interface CellIdentity {
  id: string;
  name: string;
}

export interface CellIndex<T extends CellIdentity> {
  byId: Map<string, T>;
  byName: Map<string, T>;
}

export const indexCells = <T extends CellIdentity>(cells: readonly T[]): CellIndex<T> => {
  const byId = new Map<string, T>();
  const byName = new Map<string, T>();
  cells.forEach((cell) => {
    byId.set(cell.id, cell);
    if (cell.name !== "_" && !byName.has(cell.name)) {
      byName.set(cell.name, cell);
    }
  });
  return { byId, byName };
};

export const resolveCellBinding = <T extends CellIdentity>(
  binding: CellBindingConfig | undefined,
  cells: CellIndex<T>,
): T | undefined => {
  if (!binding) {
    return undefined;
  }
  return binding.kind === "name" ? cells.byName.get(binding.value) : cells.byId.get(binding.value);
};

export const cellBindingKey = (binding: CellBindingConfig): string => {
  return `${binding.kind}\0${binding.value}`;
};
