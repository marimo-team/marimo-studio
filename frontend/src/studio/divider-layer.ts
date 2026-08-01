import {
  type Axis,
  computeLayout,
  type DividerRectangle,
  type LayoutNode,
  updateRatio,
} from "./layout.ts";

interface DividerDrag {
  id: string;
  axis: Axis;
  origin: number;
  size: number;
  ratio: number;
  frame?: number;
}

export class DividerLayer {
  private readonly elements = new Map<string, HTMLElement>();
  private drag: DividerDrag | undefined;

  constructor(
    private readonly workspace: HTMLElement,
    private readonly layer: HTMLElement,
    private readonly scrim: HTMLElement,
    private readonly tree: () => LayoutNode,
    private readonly preview: (tree: LayoutNode) => void,
    private readonly commit: (tree: LayoutNode) => void,
  ) {}

  render(dividers: DividerRectangle[]): void {
    const active = new Set(dividers.map((divider) => divider.id));
    for (const [id, element] of this.elements) {
      if (!active.has(id)) {
        element.remove();
        this.elements.delete(id);
      }
    }
    for (const divider of dividers) {
      let element = this.elements.get(divider.id);
      if (!element) {
        element = document.createElement("div");
        element.className = "studio-divider";
        element.tabIndex = 0;
        element.setAttribute("role", "separator");
        element.dataset.dividerId = divider.id;
        this.bind(element, divider.id);
        this.layer.append(element);
        this.elements.set(divider.id, element);
      }
      element.dataset.axis = divider.axis;
      element.setAttribute(
        "aria-orientation",
        divider.axis === "x" ? "vertical" : "horizontal",
      );
      element.setAttribute(
        "aria-label",
        divider.axis === "x" ? "Resize columns" : "Resize rows",
      );
      element.setAttribute("aria-valuemin", "10");
      element.setAttribute("aria-valuemax", "90");
      element.setAttribute(
        "aria-valuenow",
        String(Math.round(divider.ratio * 100)),
      );
      Object.assign(element.style, {
        left: `${divider.left}px`,
        top: `${divider.top}px`,
        width: `${divider.width}px`,
        height: `${divider.height}px`,
      });
    }
  }

  dispose(): void {
    if (this.drag?.frame !== undefined) {
      globalThis.cancelAnimationFrame(this.drag.frame);
    }
    this.drag = undefined;
  }

  private bind(element: HTMLElement, id: string): void {
    element.addEventListener("pointerdown", (event) => {
      const divider = this.divider(id);
      if (!divider) {
        return;
      }
      const workspaceBounds = this.workspace.getBoundingClientRect();
      this.drag = {
        id,
        axis: divider.axis,
        origin: divider.axis === "x"
          ? workspaceBounds.left + divider.bounds.left
          : workspaceBounds.top + divider.bounds.top,
        size: divider.axis === "x"
          ? divider.bounds.width - divider.width
          : divider.bounds.height - divider.height,
        ratio: divider.ratio,
      };
      element.setPointerCapture(event.pointerId);
      this.scrim.hidden = false;
      this.scrim.dataset.axis = divider.axis;
      this.workspace.dataset.resizing = "true";
    });
    element.addEventListener("pointermove", (event) => {
      const drag = this.drag;
      if (!drag || !element.hasPointerCapture(event.pointerId)) {
        return;
      }
      const position = drag.axis === "x" ? event.clientX : event.clientY;
      drag.ratio = (position - drag.origin) / drag.size;
      if (drag.frame === undefined) {
        drag.frame = globalThis.requestAnimationFrame(() => {
          drag.frame = undefined;
          this.preview(updateRatio(this.tree(), id, drag.ratio));
        });
      }
    });
    const finish = (save: boolean) => {
      const drag = this.drag;
      if (!drag || drag.id !== id) {
        return;
      }
      if (drag.frame !== undefined) {
        globalThis.cancelAnimationFrame(drag.frame);
      }
      this.drag = undefined;
      this.scrim.hidden = true;
      delete this.scrim.dataset.axis;
      delete this.workspace.dataset.resizing;
      if (save) {
        this.commit(updateRatio(this.tree(), id, drag.ratio));
      } else {
        this.preview(this.tree());
      }
    };
    element.addEventListener("pointerup", () => finish(true));
    element.addEventListener("pointercancel", () => finish(false));
    element.addEventListener("dblclick", () => {
      this.commit(updateRatio(this.tree(), id, 0.5));
    });
    element.addEventListener("keydown", (event) => {
      const divider = this.divider(id);
      if (!divider) {
        return;
      }
      const negative = divider.axis === "x" ? "ArrowLeft" : "ArrowUp";
      const positive = divider.axis === "x" ? "ArrowRight" : "ArrowDown";
      if (event.key !== negative && event.key !== positive) {
        return;
      }
      event.preventDefault();
      const step = event.shiftKey ? 0.1 : 0.02;
      this.commit(
        updateRatio(
          this.tree(),
          id,
          divider.ratio + (event.key === positive ? step : -step),
        ),
      );
    });
  }

  private divider(id: string): DividerRectangle | undefined {
    return computeLayout(this.tree(), {
      left: 0,
      top: 0,
      width: this.workspace.clientWidth,
      height: this.workspace.clientHeight,
    }).dividers.find((candidate) => candidate.id === id);
  }
}
