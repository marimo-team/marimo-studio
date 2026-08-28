import type { Starter } from "@marimo-studio/protocol/provider-catalog";

import { type FormEvent, type RefObject, useCallback, useEffect, useRef, useState } from "react";

import type { ViewController, ViewSnapshot } from "./controller.ts";

import { useControllerSnapshot } from "../../shared/useControllerSnapshot.ts";
import { preferredStarterId } from "./starters.ts";

export type ViewMenuPanel = "create" | "list" | "remove";

interface ViewMenuActions {
  beginCreate: () => void;
  beginRemoval: (view: string) => void;
  cancelCreate: () => void;
  cancelRemoval: () => void;
  choose: (view: string) => void;
  closeMenu: () => void;
  remove: () => void;
  retryStarters: () => void;
  setName: (name: string) => void;
  setStarter: (starter: string) => void;
  submitCreate: (event: FormEvent) => void;
  toggled: (open: boolean) => void;
}

interface ViewMenuRefs {
  confirmRemoval: RefObject<HTMLButtonElement | null>;
  input: RefObject<HTMLInputElement | null>;
  menu: RefObject<HTMLDetailsElement | null>;
  newView: RefObject<HTMLButtonElement | null>;
  popover: RefObject<HTMLDivElement | null>;
  trigger: RefObject<HTMLElement | null>;
}

interface ViewMenuRow {
  current: boolean;
  default: boolean;
  name: string;
  removing: boolean;
  selecting: boolean;
}

export interface ViewMenuModel {
  actions: ViewMenuActions;
  canRemove: boolean;
  createLabel: string;
  name: string;
  popoverMode: "manual" | undefined;
  starter: string;
  starters: readonly Starter[];
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

const panelFor = (creating: boolean, removing: string | undefined): ViewMenuPanel => {
  if (removing) {
    return "remove";
  }
  if (creating) {
    return "create";
  }
  return "list";
};

const MUTATION_LABELS = {
  create: { busy: "Creating…", idle: "Create" },
  remove: { busy: "Removing…", idle: "Remove" },
} as const;

export const useViewMenu = (controller: ViewController): ViewMenuModel => {
  const snapshot = useControllerSnapshot(controller);
  const menu = useRef<HTMLDetailsElement>(null);
  const trigger = useRef<HTMLElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const newView = useRef<HTMLButtonElement>(null);
  const popover = useRef<HTMLDivElement>(null);
  const confirmRemoval = useRef<HTMLButtonElement>(null);
  const removalView = useRef<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [starter, setStarter] = useState("");

  useEffect(() => {
    if (
      snapshot.starters.some(
        (candidate) => candidate.id === starter && candidate.availability.available,
      )
    ) {
      return;
    }
    setStarter(preferredStarterId(snapshot.starters, snapshot.defaultStarter));
  }, [snapshot.defaultStarter, snapshot.starters, starter]);

  useEffect(() => {
    if (creating) {
      input.current?.focus();
    }
  }, [creating]);

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
  }, [creating, snapshot.removing, syncPopover]);

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
  const submitCreate = useCallback(
    (event: FormEvent) => {
      event.preventDefault();
      void controller.create(name, starter).then((created) => {
        if (!created) {
          return;
        }
        setName("");
        setCreating(false);
        close();
      });
    },
    [close, controller, name, starter],
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
    setCreating(true);
    void controller.ensureStarterCatalog();
  }, [controller]);
  const retryStarters = useCallback(() => {
    void controller.ensureStarterCatalog();
  }, [controller]);
  const cancelCreate = useCallback(() => {
    if (snapshot.creating) {
      return;
    }
    setCreating(false);
    setName("");
    controller.dismiss();
    focusNextFrame(() => newView.current);
  }, [controller, snapshot.creating]);
  const beginRemoval = useCallback(
    (view: string) => {
      setCreating(false);
      controller.cancelPendingSelection();
      removalView.current = view;
      controller.beginRemoval(view);
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
      if (!open && (snapshot.creating || snapshot.deleting)) {
        menu.current?.setAttribute("open", "");
        syncPopover(true);
        return;
      }
      syncPopover(open);
      if (open) {
        return;
      }
      setCreating(false);
      setName("");
      controller.dismissPanels();
    },
    [controller, snapshot.creating, snapshot.deleting, syncPopover],
  );
  const rows = snapshot.views.map((view) => ({
    current: view === snapshot.current,
    default: view === snapshot.defaultView,
    name: view,
    removing: view === snapshot.removing,
    selecting: view === snapshot.selecting,
  }));

  return {
    snapshot,
    name,
    popoverMode: VIEW_MENU_TOP_LAYER_SUPPORTED ? "manual" : undefined,
    starter,
    starters: snapshot.starters,
    canRemove: snapshot.views.length > 1,
    panel: panelFor(creating, snapshot.removing),
    createLabel: MUTATION_LABELS.create[snapshot.creating ? "busy" : "idle"],
    removeLabel: MUTATION_LABELS.remove[snapshot.deleting ? "busy" : "idle"],
    replacementDefault:
      snapshot.removing === snapshot.defaultView
        ? snapshot.views.find((view) => view !== snapshot.removing)
        : undefined,
    rows,
    refs: { confirmRemoval, input, menu, newView, popover, trigger },
    actions: {
      beginCreate,
      beginRemoval,
      cancelCreate,
      cancelRemoval,
      choose,
      closeMenu: close,
      remove,
      retryStarters,
      setName,
      setStarter,
      submitCreate,
      toggled,
    },
  };
};
