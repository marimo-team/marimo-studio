import type { ViewLanding } from "../views/transition.ts";

import { DividerLayer } from "./divider-layer.ts";
import {
  codeLayout,
  type ComputedLayout,
  computeLayout,
  defaultWorkspaceLayout,
  equalizeLayout,
  layoutForMode,
  type LayoutNode,
  needsCompactLayout,
  newViewLayout,
  type Rectangle,
  type Surface,
  visibleSurfaces,
} from "./model.ts";
import { renderPaneActions } from "./pane-actions.ts";
import { studioModeSchema, surfaceSchema, type StudioMode } from "./schema.ts";
import { applyActiveMode, type ActiveLayout, LayoutStorage } from "./storage.ts";

const computeVisibleLayout = (
  tree: LayoutNode,
  bounds: Rectangle,
  active: Surface | null,
): ComputedLayout => {
  if (active) {
    return {
      panes: new Map<Surface, Rectangle>([[active, bounds]]),
      dividers: [],
    };
  }
  return computeLayout(tree, bounds);
};

export class LayoutController {
  private mode: StudioMode = "split";
  private code: LayoutNode = codeLayout();
  private workspaceTree: LayoutNode = defaultWorkspaceLayout();
  private compactSurface: Surface = "notebook";
  private arranging = false;
  private view: string;
  private readonly storage: LayoutStorage;
  private readonly dividers: DividerLayer;
  private readonly resizeObserver: ResizeObserver;
  private readonly onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape" && this.arranging) {
      this.arranging = false;
      this.render();
    }
  };

  constructor(
    private readonly root: HTMLElement,
    private readonly workspace: HTMLElement,
    dividerLayer: HTMLElement,
    scrim: HTMLElement,
    private readonly panes: Map<Surface, HTMLElement>,
    private readonly compactTabs: HTMLElement,
    storagePrefix: string,
    initialView: string,
    private readonly onMeasure: () => void,
  ) {
    this.view = initialView;
    this.storage = new LayoutStorage(storagePrefix);
    this.restore(initialView);
    this.dividers = new DividerLayer(
      workspace,
      dividerLayer,
      scrim,
      () => this.tree,
      (tree) => this.render(tree, false),
      (tree) => {
        this.setTree(tree);
        this.commit();
      },
    );
    this.bindControls();
    this.resizeObserver = new ResizeObserver(() => this.render());
    this.resizeObserver.observe(workspace);
    this.render();
  }

  switchView(view: string, landing: ViewLanding): void {
    const active = { mode: this.mode, compact: this.compactSurface };
    this.persist();
    this.view = view;
    if (landing === "authoring") {
      this.mode = "workspace";
      this.code = codeLayout();
      this.workspaceTree = newViewLayout();
      this.compactSurface = "source";
      this.arranging = false;
      this.persist();
    } else if (landing === "split") {
      this.restore(view);
      this.mode = "split";
      this.compactSurface = "notebook";
      this.arranging = false;
      this.persist();
    } else {
      this.restore(view, active);
      this.persist();
    }
    this.render();
  }

  reveal(surface: Surface): void {
    const visible = visibleSurfaces(this.tree);
    if (!visible.includes(surface)) {
      this.mode = this.modeForSurface(surface);
    }
    this.compactSurface = surface;
    this.arranging = false;
    this.commit();
    this.closeMenus();
  }

  dispose(): void {
    this.persist();
    this.resizeObserver.disconnect();
    this.dividers.dispose();
    globalThis.removeEventListener("keydown", this.onKeyDown);
  }

  private bindControls(): void {
    this.root.querySelectorAll<HTMLButtonElement>("[data-studio-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        const mode = studioModeSchema.safeParse(button.dataset.studioMode);
        if (!mode.success || mode.data === "workspace") {
          return;
        }
        this.mode = mode.data;
        this.arranging = false;
        this.ensureCompactSurface();
        this.commit();
        this.closeMenus();
      });
    });
    this.root.querySelectorAll<HTMLButtonElement>("[data-layout-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.dataset.layoutAction;
        if (!this.applyLayoutAction(action)) {
          return;
        }
        this.commit();
        this.closeMenus();
      });
    });
    this.compactTabs
      .querySelectorAll<HTMLButtonElement>("[data-compact-surface]")
      .forEach((button) => {
        button.addEventListener("click", () => {
          const surface = surfaceSchema.safeParse(button.dataset.compactSurface);
          if (surface.success) {
            this.compactSurface = surface.data;
            this.persist();
            this.render();
          }
        });
      });
    this.root.querySelectorAll<HTMLDetailsElement>("[data-pane-menu]").forEach((menu) => {
      menu.addEventListener("toggle", () => {
        const target = menu.dataset.paneMenu;
        const surface = surfaceSchema.safeParse(target);
        if (menu.open && surface.success) {
          this.renderPaneActions(menu, surface.data);
        }
      });
    });
    globalThis.addEventListener("keydown", this.onKeyDown);
  }

  private renderPaneActions(menu: HTMLDetailsElement, target: Surface): void {
    renderPaneActions(menu, target, this.tree, ({ tree, compact }) => {
      this.mode = "workspace";
      this.workspaceTree = tree;
      const visible = visibleSurfaces(tree);
      if (compact) {
        this.compactSurface = compact;
      } else if (!visible.includes(this.compactSurface)) {
        this.compactSurface = visible[0];
      }
      this.commit();
      this.closeMenus();
    });
  }

  private render(tree = this.tree, measure = true): void {
    const width = this.workspace.clientWidth;
    const height = this.workspace.clientHeight;
    if (width <= 0 || height <= 0) {
      return;
    }
    const bounds = { left: 0, top: 0, width, height };
    const compact = needsCompactLayout(tree, bounds);
    const visible = visibleSurfaces(tree);
    if (!visible.includes(this.compactSurface)) {
      this.compactSurface = visible[0];
    }
    const active = compact ? this.compactSurface : null;
    this.renderCompactTabs(compact, visible);
    const layout = computeVisibleLayout(tree, bounds, active);
    for (const [surface, pane] of this.panes) {
      const rectangle = layout.panes.get(surface);
      pane.hidden = rectangle === undefined;
      pane.inert = rectangle === undefined;
      if (rectangle) {
        Object.assign(pane.style, {
          left: `${rectangle.left}px`,
          top: `${rectangle.top}px`,
          width: `${rectangle.width}px`,
          height: `${rectangle.height}px`,
        });
      }
    }
    this.dividers.render(layout.dividers);
    this.workspace.dataset.compact = String(compact);
    this.workspace.dataset.arranging = String(this.arranging);
    this.renderModes();
    this.renderWorkspaceControls();
    this.renderPreviewControls(layout.panes.has("preview"));
    if (measure) {
      this.onMeasure();
    }
  }

  private renderCompactTabs(compact: boolean, visible: Surface[]): void {
    this.compactTabs.hidden = !compact || visible.length < 2;
    this.compactTabs
      .querySelectorAll<HTMLButtonElement>("[data-compact-surface]")
      .forEach((button) => {
        const surface = surfaceSchema.safeParse(button.dataset.compactSurface);
        button.hidden = !surface.success || !visible.includes(surface.data);
        button.setAttribute(
          "aria-pressed",
          String(surface.success && surface.data === this.compactSurface),
        );
      });
  }

  private commit(): void {
    this.persist();
    this.render();
  }

  private persist(): void {
    this.storage.write(this.view, {
      mode: this.mode,
      code: this.code,
      workspace: this.workspaceTree,
      compact: this.compactSurface,
    });
  }

  private restore(view: string, active?: ActiveLayout): void {
    const saved = this.storage.read(view);
    const state = active ? applyActiveMode(saved, active) : saved;
    this.mode = state.mode;
    this.code = state.code;
    this.workspaceTree = state.workspace;
    this.compactSurface = state.compact;
    this.arranging = false;
  }

  private get tree(): LayoutNode {
    return layoutForMode(this.mode, this.code, this.workspaceTree);
  }

  private setTree(tree: LayoutNode): void {
    if (this.mode === "code") {
      this.code = tree;
      return;
    }
    if (this.mode !== "workspace") {
      this.mode = "workspace";
    }
    this.workspaceTree = tree;
  }

  private applyLayoutAction(action: string | undefined): boolean {
    switch (action) {
      case "workspace":
        this.mode = "workspace";
        this.arranging = false;
        this.ensureCompactSurface();
        return true;
      case "arrange":
        this.mode = "workspace";
        this.arranging = !this.arranging;
        this.ensureCompactSurface();
        return true;
      case "equalize":
        if (this.mode === "code") {
          this.code = equalizeLayout(this.code);
        } else {
          this.mode = "workspace";
          this.workspaceTree = equalizeLayout(this.workspaceTree);
        }
        return true;
      case "reset":
        this.mode = "workspace";
        this.workspaceTree = defaultWorkspaceLayout();
        this.compactSurface = "notebook";
        this.arranging = false;
        return true;
      default:
        return false;
    }
  }

  private modeForSurface(surface: Surface): StudioMode {
    if (surface === "source") {
      return "code";
    }
    return surface;
  }

  private ensureCompactSurface(): void {
    const visible = visibleSurfaces(this.tree);
    if (!visible.includes(this.compactSurface)) {
      this.compactSurface = visible[0];
    }
  }

  private renderModes(): void {
    this.root.querySelectorAll<HTMLButtonElement>("[data-studio-mode]").forEach((button) => {
      const mode = studioModeSchema.safeParse(button.dataset.studioMode);
      const selected = mode.success && mode.data === this.mode;
      button.setAttribute("aria-pressed", String(selected));
    });
    this.root.dataset.mode = this.mode;
  }

  private renderWorkspaceControls(): void {
    const menu = this.root.querySelector<HTMLDetailsElement>("[data-layout-menu]");
    if (!menu) {
      return;
    }
    menu.dataset.active = String(this.mode === "workspace");
    menu.dataset.arranging = String(this.arranging);
    const workspace = menu.querySelector<HTMLButtonElement>("[data-layout-action='workspace']");
    workspace?.setAttribute("aria-current", this.mode === "workspace" ? "true" : "false");
    const arrange = menu.querySelector<HTMLButtonElement>("[data-layout-action='arrange']");
    arrange?.setAttribute("aria-pressed", String(this.arranging));
  }

  private renderPreviewControls(visible: boolean): void {
    this.root.querySelectorAll<HTMLElement>("[data-preview-control]").forEach((control) => {
      control.hidden = !visible;
    });
  }

  private closeMenus(): void {
    this.root
      .querySelectorAll<HTMLDetailsElement>("details[open]")
      .forEach((menu) => menu.removeAttribute("open"));
  }
}
