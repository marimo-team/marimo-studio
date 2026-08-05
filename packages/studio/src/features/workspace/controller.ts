import type { ViewLanding } from "../views/transition.ts";
import type { StudioMode } from "./schema.ts";

import { assertNever } from "../../shared/assertNever.ts";
import {
  codeLayout,
  defaultWorkspaceLayout,
  equalizeLayout,
  layoutForMode,
  type LayoutNode,
  newViewLayout,
  type Surface,
  visibleSurfaces,
} from "./model.ts";
import { applyActiveMode, type ActiveLayout, type LayoutState, LayoutStorage } from "./storage.ts";

export interface LayoutSnapshot extends LayoutState {
  arranging: boolean;
  tree: LayoutNode;
}

export interface PaneActionResult {
  tree: LayoutNode;
  compact?: Surface;
}

type Listener = () => void;

export class LayoutController {
  private view: string;
  private mode: StudioMode = "split";
  private code: LayoutNode = codeLayout();
  private workspace: LayoutNode = defaultWorkspaceLayout();
  private compact: Surface = "notebook";
  private arranging = false;
  private transientTree: LayoutNode | undefined;
  private snapshot!: LayoutSnapshot;
  private readonly listeners = new Set<Listener>();
  private readonly storage: LayoutStorage;

  constructor(storagePrefix: string, initialView: string) {
    this.view = initialView;
    this.storage = new LayoutStorage(storagePrefix);
    this.restore(initialView, { mode: "split", compact: "notebook" });
    this.updateSnapshot();
  }

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): LayoutSnapshot => this.snapshot;

  switchView(view: string, landing: ViewLanding): void {
    const active = { mode: this.mode, compact: this.compact };
    this.persist();
    this.view = view;
    if (landing === "authoring") {
      this.mode = "workspace";
      this.code = codeLayout();
      this.workspace = newViewLayout();
      this.compact = "source";
      this.arranging = false;
    } else if (landing === "split") {
      this.restore(view);
      this.mode = "split";
      this.compact = "notebook";
      this.arranging = false;
    } else {
      this.restore(view, active);
    }
    this.commit();
  }

  selectMode(mode: Exclude<StudioMode, "workspace">): void {
    this.mode = mode;
    this.arranging = false;
    this.ensureCompactSurface();
    this.commit();
  }

  reveal(surface: Surface): void {
    if (!visibleSurfaces(this.tree).includes(surface)) {
      this.mode = surface === "source" ? "code" : surface;
    }
    this.compact = surface;
    this.arranging = false;
    this.commit();
  }

  selectCompact(surface: Surface): void {
    if (!visibleSurfaces(this.tree).includes(surface)) {
      return;
    }
    this.compact = surface;
    this.commit();
  }

  applyAction(action: "workspace" | "arrange" | "equalize" | "reset"): void {
    switch (action) {
      case "workspace":
        this.mode = "workspace";
        this.arranging = false;
        this.ensureCompactSurface();
        break;
      case "arrange":
        this.mode = "workspace";
        this.arranging = !this.arranging;
        this.ensureCompactSurface();
        break;
      case "equalize":
        if (this.mode === "code") {
          this.code = equalizeLayout(this.code);
        } else {
          this.mode = "workspace";
          this.workspace = equalizeLayout(this.workspace);
        }
        break;
      case "reset":
        this.mode = "workspace";
        this.workspace = defaultWorkspaceLayout();
        this.compact = "notebook";
        this.arranging = false;
        break;
      default:
        assertNever(action);
    }
    this.commit();
  }

  applyPaneAction({ tree, compact }: PaneActionResult): void {
    this.mode = "workspace";
    this.workspace = tree;
    const visible = visibleSurfaces(tree);
    if (compact) {
      this.compact = compact;
    } else if (!visible.includes(this.compact)) {
      this.compact = visible[0];
    }
    this.commit();
  }

  preview(tree: LayoutNode): void {
    this.transientTree = tree;
    this.publish();
  }

  resize(tree: LayoutNode): void {
    this.setTree(tree);
    this.commit();
  }

  cancelPreview(): void {
    if (this.transientTree) {
      this.transientTree = undefined;
      this.publish();
    }
  }

  stopArranging(): void {
    if (this.arranging) {
      this.arranging = false;
      this.publish();
    }
  }

  dispose(): void {
    this.persist();
    this.listeners.clear();
  }

  private get tree(): LayoutNode {
    return this.transientTree ?? layoutForMode(this.mode, this.code, this.workspace);
  }

  private commit(): void {
    this.transientTree = undefined;
    this.ensureCompactSurface();
    this.persist();
    this.publish();
  }

  private setTree(tree: LayoutNode): void {
    if (this.mode === "code") {
      this.code = tree;
      return;
    }
    if (this.mode !== "workspace") {
      this.mode = "workspace";
    }
    this.workspace = tree;
  }

  private ensureCompactSurface(): void {
    const visible = visibleSurfaces(this.tree);
    if (!visible.includes(this.compact)) {
      this.compact = visible[0];
    }
  }

  private persist(): void {
    this.storage.write(this.view, {
      mode: this.mode,
      code: this.code,
      workspace: this.workspace,
      compact: this.compact,
    });
  }

  private restore(view: string, active?: ActiveLayout): void {
    const saved = this.storage.read(view);
    const state = active ? applyActiveMode(saved, active) : saved;
    this.mode = state.mode;
    this.code = state.code;
    this.workspace = state.workspace;
    this.compact = state.compact;
    this.arranging = false;
    this.transientTree = undefined;
  }

  private publish(): void {
    this.updateSnapshot();
    this.listeners.forEach((listener) => listener());
  }

  private updateSnapshot(): void {
    this.snapshot = {
      mode: this.mode,
      code: this.code,
      workspace: this.workspace,
      compact: this.compact,
      arranging: this.arranging,
      tree: this.tree,
    };
  }
}
