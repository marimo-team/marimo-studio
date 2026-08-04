import { codeLayout, defaultWorkspaceLayout, layoutForMode, visibleSurfaces } from "./model.ts";
import { type LayoutNode, storedLayoutCodec, type StudioMode, type Surface } from "./schema.ts";

export type LayoutState = {
  mode: StudioMode;
  code: LayoutNode;
  workspace: LayoutNode;
  compact: Surface;
};

export type ActiveLayout = Pick<LayoutState, "mode" | "compact">;

export const applyActiveMode = (saved: LayoutState, active: ActiveLayout): LayoutState => {
  const visible = visibleSurfaces(layoutForMode(active.mode, saved.code, saved.workspace));
  let compact = active.compact;
  if (!visible.includes(compact)) {
    compact = visible.includes(saved.compact) ? saved.compact : visible[0];
  }
  return { ...saved, mode: active.mode, compact };
};

const initialState = (): LayoutState => ({
  mode: "split",
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
