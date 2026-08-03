import { defaultLayout, visibleSurfaces } from "./model.ts";
import { type LayoutNode, storedLayoutCodec, type Surface } from "./schema.ts";

export type LayoutState = {
  tree: LayoutNode;
  focused: Surface | null;
  compact: Surface;
};

const initialState = (): LayoutState => ({
  tree: defaultLayout(),
  focused: null,
  compact: "notebook",
});

export class LayoutStorage {
  constructor(private readonly prefix: string) {}

  read(view: string): LayoutState {
    const raw = globalThis.localStorage.getItem(this.key(view));
    if (!raw) {
      return initialState();
    }
    const result = storedLayoutCodec.safeDecode(raw);
    if (!result.success) {
      return initialState();
    }
    const { tree, focused, compact } = result.data;
    const visible = visibleSurfaces(tree);
    return {
      tree,
      focused: focused && visible.includes(focused) ? focused : null,
      compact: compact && visible.includes(compact) ? compact : visible[0],
    };
  }

  write(view: string, state: LayoutState): void {
    const stored = { schema: 1 as const, ...state };
    globalThis.localStorage.setItem(this.key(view), storedLayoutCodec.encode(stored));
  }

  private key(view: string): string {
    return `${this.prefix}:${view}`;
  }
}
