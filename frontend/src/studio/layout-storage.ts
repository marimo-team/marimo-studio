import {
  defaultLayout,
  type LayoutNode,
  parseLayout,
  type Surface,
  visibleSurfaces,
} from "./layout.ts";

export interface LayoutState {
  tree: LayoutNode;
  focused: Surface | null;
  compact: Surface;
}

interface StoredLayout extends LayoutState {
  schema: 1;
}

const isSurface = (value: unknown): value is Surface =>
  value === "notebook" || value === "source" || value === "preview";

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
    try {
      const value = JSON.parse(raw) as Record<string, unknown>;
      const tree = parseLayout(JSON.stringify(value.tree));
      if (value.schema !== 1 || !tree) {
        return initialState();
      }
      return {
        tree,
        focused: isSurface(value.focused) ? value.focused : null,
        compact: isSurface(value.compact)
          ? value.compact
          : visibleSurfaces(tree)[0],
      };
    } catch {
      return initialState();
    }
  }

  write(view: string, state: LayoutState): void {
    const stored: StoredLayout = { schema: 1, ...state };
    globalThis.localStorage.setItem(this.key(view), JSON.stringify(stored));
  }

  private key(view: string): string {
    return `${this.prefix}:${view}`;
  }
}
