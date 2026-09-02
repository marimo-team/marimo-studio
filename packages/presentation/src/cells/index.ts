export interface CellIdentity {
  id: string;
}

export interface CellIndex<T extends CellIdentity> {
  byId: Map<string, T>;
}

export const indexCells = <T extends CellIdentity>(cells: readonly T[]): CellIndex<T> => ({
  byId: new Map(cells.map((cell) => [cell.id, cell])),
});
