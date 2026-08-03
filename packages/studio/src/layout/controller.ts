import { DividerLayer } from "./divider-layer.ts";
import {
  computeLayout,
  defaultLayout,
  equalizeLayout,
  type LayoutNode,
  needsCompactLayout,
  newViewLayout,
  splitSurface,
  type Surface,
  visibleSurfaces,
} from "./model.ts";
import { renderPaneActions } from "./pane-actions.ts";
import { surfaceSchema } from "./schema.ts";
import { LayoutStorage } from "./storage.ts";

export class LayoutController {
  private tree: LayoutNode = defaultLayout();
  private focused: Surface | null = null;
  private compactSurface: Surface = "notebook";
  private view: string;
  private readonly storage: LayoutStorage;
  private readonly dividers: DividerLayer;
  private readonly resizeObserver: ResizeObserver;
  private readonly onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape" && this.focused) {
      this.focused = null;
      this.commit();
    }
  };

  constructor(
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
        this.tree = tree;
        this.commit();
      },
    );
    this.bindControls();
    this.resizeObserver = new ResizeObserver(() => this.render());
    this.resizeObserver.observe(workspace);
    this.render();
  }

  switchView(view: string, created = false): void {
    this.persist();
    this.view = view;
    if (created) {
      this.tree = newViewLayout();
      this.focused = null;
      this.compactSurface = "source";
      this.persist();
    } else {
      this.restore(view);
    }
    this.render();
  }

  reveal(surface: Surface): void {
    if (!visibleSurfaces(this.tree).includes(surface)) {
      const target = this.focused ?? this.compactSurface ?? visibleSurfaces(this.tree)[0];
      this.tree = splitSurface(this.tree, target, surface, "right");
    }
    this.focused = null;
    this.compactSurface = surface;
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
    document.querySelectorAll<HTMLButtonElement>("[data-layout-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.dataset.layoutAction;
        if (action === "equalize") {
          this.tree = equalizeLayout(this.tree);
        } else if (action === "reset") {
          this.tree = defaultLayout();
          this.focused = null;
          this.compactSurface = "notebook";
        } else {
          return;
        }
        this.commit();
        this.closeMenus();
      });
    });
    document.querySelectorAll<HTMLButtonElement>("[data-focus-surface]").forEach((button) => {
      button.addEventListener("click", () => {
        const surface = surfaceSchema.safeParse(button.dataset.focusSurface);
        if (!surface.success) {
          return;
        }
        this.focused = this.focused === surface.data ? null : surface.data;
        this.compactSurface = surface.data;
        this.commit();
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
    document.querySelectorAll<HTMLDetailsElement>("[data-pane-menu]").forEach((menu) => {
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
      this.tree = tree;
      this.focused = null;
      const visible = visibleSurfaces(tree);
      this.compactSurface =
        compact ?? (visible.includes(this.compactSurface) ? this.compactSurface : visible[0]);
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
    const active = this.focused ?? (compact ? this.compactSurface : null);
    this.renderCompactTabs(compact, visible);
    const layout = active
      ? { panes: new Map([[active, bounds]]), dividers: [] }
      : computeLayout(tree, bounds);
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
    this.workspace.dataset.focused = this.focused ?? "";
    if (measure) {
      this.onMeasure();
    }
  }

  private renderCompactTabs(compact: boolean, visible: Surface[]): void {
    this.compactTabs.hidden = !compact;
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
      tree: this.tree,
      focused: this.focused,
      compact: this.compactSurface,
    });
  }

  private restore(view: string): void {
    const state = this.storage.read(view);
    this.tree = state.tree;
    this.focused = state.focused;
    this.compactSurface = state.compact;
  }

  private closeMenus(): void {
    document
      .querySelectorAll<HTMLDetailsElement>("details[open]")
      .forEach((menu) => menu.removeAttribute("open"));
  }
}
