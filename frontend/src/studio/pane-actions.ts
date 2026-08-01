import {
  closeSurface,
  type LayoutNode,
  type Placement,
  splitSurface,
  type Surface,
  swapSurfaces,
  visibleSurfaces,
} from "./layout.ts";

interface PaneActionResult {
  tree: LayoutNode;
  compact?: Surface;
}

const SURFACES: readonly Surface[] = ["notebook", "source", "preview"];
const PLACEMENTS: readonly {
  value: Placement;
  label: string;
  relation: string;
}[] = [
  { value: "left", label: "Left", relation: "to the left of" },
  { value: "right", label: "Right", relation: "to the right of" },
  { value: "above", label: "Above", relation: "above" },
  { value: "below", label: "Below", relation: "below" },
];

const label = (surface: Surface): string =>
  surface === "notebook"
    ? "Notebook"
    : surface === "source"
    ? "Source"
    : "Preview";

const menuButton = (
  text: string,
  onClick: () => void,
): HTMLButtonElement => {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "studio-menu-item";
  button.textContent = text;
  button.addEventListener("click", onClick);
  return button;
};

const separator = (): HTMLDivElement => {
  const element = document.createElement("div");
  element.className = "studio-menu-separator";
  return element;
};

export const renderPaneActions = (
  menu: HTMLDetailsElement,
  target: Surface,
  tree: LayoutNode,
  apply: (result: PaneActionResult) => void,
): void => {
  const actions = menu.querySelector<HTMLElement>("[data-pane-actions]");
  if (!actions) {
    return;
  }
  const visible = visibleSurfaces(tree);
  const missing = SURFACES.filter((surface) => !visible.includes(surface));
  const fragment = document.createDocumentFragment();

  for (const [index, surface] of missing.entries()) {
    if (index > 0) {
      fragment.append(separator());
    }
    const heading = document.createElement("strong");
    heading.className = "studio-menu-heading";
    heading.textContent = `Add ${label(surface)}`;
    fragment.append(heading);

    const placements = document.createElement("div");
    placements.className = "studio-placement-grid";
    for (const placement of PLACEMENTS) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "studio-menu-item studio-placement-action";
      button.dataset.placement = placement.value;
      button.setAttribute(
        "aria-label",
        `Add ${label(surface)} ${placement.relation} ${label(target)}`,
      );
      const icon = document.createElement("span");
      icon.className = "studio-placement-icon";
      icon.dataset.placement = placement.value;
      icon.setAttribute("aria-hidden", "true");
      const text = document.createElement("span");
      text.textContent = placement.label;
      button.append(icon, text);
      button.addEventListener("click", () => {
        apply({
          tree: splitSurface(tree, target, surface, placement.value),
          compact: surface,
        });
      });
      placements.append(button);
    }
    fragment.append(placements);
  }

  const peers = visible.filter((surface) => surface !== target);
  if (peers.length > 0) {
    if (missing.length > 0) {
      fragment.append(separator());
    }
    const heading = document.createElement("strong");
    heading.className = "studio-menu-heading";
    heading.textContent = "Arrange";
    fragment.append(heading);
    for (const surface of peers) {
      fragment.append(
        menuButton(`Swap with ${label(surface)}`, () => {
          apply({ tree: swapSurfaces(tree, target, surface) });
        }),
      );
    }
    fragment.append(separator());
    fragment.append(
      menuButton("Close pane", () => {
        apply({ tree: closeSurface(tree, target) });
      }),
    );
  }

  actions.replaceChildren(fragment);
};
