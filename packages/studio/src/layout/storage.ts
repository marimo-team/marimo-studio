import { codeLayout, defaultWorkspaceLayout, layoutForMode, visibleSurfaces } from "./model.ts";
import { type LayoutNode, storedLayoutCodec, type StudioMode, type Surface } from "./schema.ts";

export type LayoutState = {
  mode: StudioMode;
  code: LayoutNode;
  workspace: LayoutNode;
  compact: Surface;
};

const initialState = (): LayoutState => ({
  mode: "notebook",
  code: codeLayout(),
  workspace: defaultWorkspaceLayout(),
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
    const { mode, code, workspace, compact } = result.data;
    const visible = visibleSurfaces(layoutForMode(mode, code, workspace));
    return {
      mode,
      code,
      workspace,
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
