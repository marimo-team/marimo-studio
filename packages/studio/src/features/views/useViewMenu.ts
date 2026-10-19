import { type FormEvent, type RefObject, useCallback, useEffect, useRef, useState } from "react";

import type { ViewController, ViewSnapshot } from "./controller.ts";

import { useControllerSnapshot } from "../../shared/useControllerSnapshot.ts";
import { useViewDraft, type ViewDraftModel } from "./useViewDraft.ts";

export type ViewMenuPanel = "list" | "remove";

interface ViewMenuActions {
  beginCreate: () => void;
  beginRemoval: (view: string, catalogGeneration: string, generation: string) => void;
  cancelCreate: () => void;
  cancelRemoval: () => void;
  choose: (view: string) => void;
  closeMenu: () => void;
  remove: () => void;
  retryStarters: () => void;
  submitCreate: (event: FormEvent) => void;
  toggled: (open: boolean) => void;
}

interface ViewMenuRefs {
  confirmRemoval: RefObject<HTMLButtonElement | null>;
  menu: RefObject<HTMLDetailsElement | null>;
  popover: RefObject<HTMLDivElement | null>;
  trigger: RefObject<HTMLElement | null>;
}

interface ViewMenuRow {
  catalogGeneration?: string;
  current: boolean;
  default: boolean;
  generation?: string;
  name: string;
  removing: boolean;
  selecting: boolean;
}

export interface ViewMenuModel {
  actions: ViewMenuActions;
  canRemove: boolean;
  createLabel: string;
  creating: boolean;
  draft: ViewDraftModel;
  popoverMode: "manual" | undefined;
  panel: ViewMenuPanel;
  refs: ViewMenuRefs;
  removeLabel: string;
  replacementDefault?: string;
  rows: readonly ViewMenuRow[];
  snapshot: ViewSnapshot;
}

const focusNextFrame = (element: () => HTMLElement | null | undefined): void => {
  globalThis.requestAnimationFrame(() => element()?.focus());
};

const POPOVER_VIEWPORT_GAP = 8;
const VIEW_MENU_TOP_LAYER_SUPPORTED =
  "showPopover" in HTMLElement.prototype && "hidePopover" in HTMLElement.prototype;

const positionPopover = (popover: HTMLDivElement, trigger: HTMLElement): void => {
  const triggerRect = trigger.getBoundingClientRect();
  popover.style.setProperty("--studio-view-menu-left", `${triggerRect.left}px`);
  popover.style.setProperty("--studio-view-menu-top", `${triggerRect.bottom + 6}px`);

  const popoverRect = popover.getBoundingClientRect();
  const left = Math.max(
    POPOVER_VIEWPORT_GAP,
    Math.min(triggerRect.left, globalThis.innerWidth - popoverRect.width - POPOVER_VIEWPORT_GAP),
  );
  popover.style.setProperty("--studio-view-menu-left", `${left}px`);
};

const panelFor = (removing: string | undefined): ViewMenuPanel => (removing ? "remove" : "list");

const MUTATION_LABELS = {
  create: { busy: "Creating…", idle: "Create view" },
  remove: { busy: "Removing…", idle: "Remove" },
} as const;

export const useViewMenu = (controller: ViewController): ViewMenuModel => {
  const snapshot = useControllerSnapshot(controller);
  const menu = useRef<HTMLDetailsElement>(null);
  const trigger = useRef<HTMLElement>(null);
  const popover = useRef<HTMLDivElement>(null);
  const confirmRemoval = useRef<HTMLButtonElement>(null);
  const creationCatalogGeneration = useRef<string | undefined>(undefined);
  const removalView = useRef<string | null>(null);
  const [creating, setCreating] = useState(false);
  const draft = useViewDraft({
    starters: snapshot.starters,
    defaultStarter: snapshot.defaultStarter,
  });

  const draftName = draft.value.name;
  useEffect(() => {
    controller.clearCreateError();
  }, [controller, draftName]);

  useEffect(() => {
    if (snapshot.removing) {
      confirmRemoval.current?.focus();
    }
  }, [snapshot.removing]);

  const syncPopover = useCallback((open: boolean) => {
    const element = popover.current;
    const anchor = trigger.current;
    if (!element || !anchor || !VIEW_MENU_TOP_LAYER_SUPPORTED) {
      return;
    }
    if (!open) {
      if (element.matches(":popover-open")) {
        element.hidePopover();
      }
      return;
    }
    if (!element.matches(":popover-open")) {
      element.showPopover();
    }
    positionPopover(element, anchor);
  }, []);

  useEffect(() => {
    const reposition = () => {
      if (menu.current?.open) {
        syncPopover(true);
      }
    };
    globalThis.addEventListener("resize", reposition);
    return () => {
      globalThis.removeEventListener("resize", reposition);
      syncPopover(false);
    };
  }, [syncPopover]);

  useEffect(() => {
    if (menu.current?.open) {
      syncPopover(true);
    }
  }, [snapshot.removing, syncPopover]);

  const close = useCallback(() => {
    const focusOwned = menu.current?.contains(globalThis.document.activeElement) === true;
    menu.current?.removeAttribute("open");
    syncPopover(false);
    if (focusOwned) {
      trigger.current?.focus();
    }
  }, [syncPopover]);
  const choose = useCallback(
    (view: string) => {
      close();
      void controller.choose(view);
    },
    [close, controller],
  );
  const finishCreate = useCallback(() => {
    creationCatalogGeneration.current = undefined;
    setCreating(false);
    draft.reset();
  }, [draft]);
  const submitCreate = useCallback(
    (event: FormEvent) => {
      event.preventDefault();
      const catalogGeneration = creationCatalogGeneration.current;
      if (!catalogGeneration) {
        return;
      }
      void controller.create(draft.request(catalogGeneration)).then((created) => {
        if (created) {
          finishCreate();
        }
      });
    },
    [controller, draft, finishCreate],
  );
  const remove = useCallback(() => {
    void controller.deleteSelected().then((removed) => {
      if (removed) {
        close();
      }
    });
  }, [close, controller]);
  const beginCreate = useCallback(() => {
    controller.cancelPendingSelection();
    controller.dismiss();
    close();
    creationCatalogGeneration.current = snapshot.catalogGeneration;
    setCreating(true);
    void controller.ensureStarterCatalog().then(() => {
      creationCatalogGeneration.current ??= controller.getSnapshot().catalogGeneration;
    });
  }, [close, controller, snapshot.catalogGeneration]);
  const retryStarters = useCallback(() => {
    void controller.ensureStarterCatalog().then(() => {
      creationCatalogGeneration.current ??= controller.getSnapshot().catalogGeneration;
    });
  }, [controller]);
  const cancelCreate = useCallback(() => {
    if (snapshot.creating) {
      return;
    }
    finishCreate();
    controller.dismiss();
    focusNextFrame(() => trigger.current);
  }, [controller, finishCreate, snapshot.creating]);
  const beginRemoval = useCallback(
    (view: string, catalogGeneration: string, generation: string) => {
      controller.cancelPendingSelection();
      removalView.current = view;
      controller.beginRemoval(view, catalogGeneration, generation);
    },
    [controller],
  );
  const cancelRemoval = useCallback(() => {
    if (snapshot.deleting) {
      return;
    }
    const view = removalView.current;
    controller.cancelRemoval();
    focusNextFrame(() => {
      const buttons = menu.current?.querySelectorAll<HTMLButtonElement>("[data-view-remove]");
      return (
        Array.from(buttons ?? []).find((button) => button.dataset.viewRemove === view) ??
        trigger.current
      );
    });
  }, [controller, snapshot.deleting]);
  const toggled = useCallback(
    (open: boolean) => {
      if (!open && snapshot.deleting) {
        menu.current?.setAttribute("open", "");
        syncPopover(true);
        return;
      }
      syncPopover(open);
      if (!open) {
        controller.dismissPanels();
      }
    },
    [controller, snapshot.deleting, syncPopover],
  );
  const rows = snapshot.views.map((view) => ({
    catalogGeneration: snapshot.catalogGeneration,
    current: view === snapshot.current,
    default: view === snapshot.defaultView,
    generation: snapshot.viewGenerations[view],
    name: view,
    removing: view === snapshot.removing,
    selecting: view === snapshot.selecting,
  }));

  return {
    snapshot,
    creating,
    draft,
    popoverMode: VIEW_MENU_TOP_LAYER_SUPPORTED ? "manual" : undefined,
    canRemove: snapshot.views.length > 1,
    panel: panelFor(snapshot.removing),
    createLabel: MUTATION_LABELS.create[snapshot.creating ? "busy" : "idle"],
    removeLabel: MUTATION_LABELS.remove[snapshot.deleting ? "busy" : "idle"],
    replacementDefault:
      snapshot.removing === snapshot.defaultView
        ? snapshot.views.find((view) => view !== snapshot.removing)
        : undefined,
    rows,
    refs: { confirmRemoval, menu, popover, trigger },
    actions: {
      beginCreate,
      beginRemoval,
      cancelCreate,
      cancelRemoval,
      choose,
      closeMenu: close,
      remove,
      retryStarters,
      submitCreate,
      toggled,
    },
  };
};
