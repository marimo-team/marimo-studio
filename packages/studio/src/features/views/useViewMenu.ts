import { type FormEvent, type RefObject, useCallback, useEffect, useRef, useState } from "react";

import type { ViewController, ViewSnapshot } from "./controller.ts";

import { useControllerSnapshot } from "../../shared/useControllerSnapshot.ts";

export type ViewMenuPanel = "create" | "list" | "remove";

interface ViewMenuActions {
  beginCreate: () => void;
  beginRemoval: (view: string, origin: HTMLButtonElement) => void;
  cancelCreate: () => void;
  cancelRemoval: () => void;
  choose: (view: string) => void;
  remove: () => void;
  setName: (name: string) => void;
  submitCreate: (event: FormEvent) => void;
  toggled: (open: boolean) => void;
}

interface ViewMenuRefs {
  confirmRemoval: RefObject<HTMLButtonElement | null>;
  input: RefObject<HTMLInputElement | null>;
  menu: RefObject<HTMLDetailsElement | null>;
  newView: RefObject<HTMLButtonElement | null>;
  trigger: RefObject<HTMLElement | null>;
}

interface ViewMenuRow {
  current: boolean;
  name: string;
  removing: boolean;
}

export interface ViewMenuModel {
  actions: ViewMenuActions;
  canRemove: boolean;
  createLabel: string;
  name: string;
  panel: ViewMenuPanel;
  refs: ViewMenuRefs;
  removeLabel: string;
  rows: readonly ViewMenuRow[];
  snapshot: ViewSnapshot;
}

const focusNextFrame = (element: () => HTMLElement | null | undefined): void => {
  globalThis.requestAnimationFrame(() => element()?.focus());
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
  const confirmRemoval = useRef<HTMLButtonElement>(null);
  const removalOrigin = useRef<HTMLButtonElement | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

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

  const close = useCallback(() => {
    menu.current?.removeAttribute("open");
    trigger.current?.focus();
  }, []);
  const choose = useCallback(
    (view: string) => {
      void controller.choose(view).then((selected) => {
        if (selected) {
          close();
        }
      });
    },
    [close, controller],
  );
  const submitCreate = useCallback(
    (event: FormEvent) => {
      event.preventDefault();
      void controller.create(name).then((created) => {
        if (!created) {
          return;
        }
        setName("");
        setCreating(false);
        close();
      });
    },
    [close, controller, name],
  );
  const remove = useCallback(() => {
    void controller.deleteSelected().then((removed) => {
      if (removed) {
        close();
      }
    });
  }, [close, controller]);
  const beginCreate = useCallback(() => {
    controller.dismiss();
    setCreating(true);
  }, [controller]);
  const cancelCreate = useCallback(() => {
    setCreating(false);
    setName("");
    controller.dismiss();
    focusNextFrame(() => newView.current);
  }, [controller]);
  const beginRemoval = useCallback(
    (view: string, origin: HTMLButtonElement) => {
      setCreating(false);
      removalOrigin.current = origin;
      controller.beginRemoval(view);
    },
    [controller],
  );
  const cancelRemoval = useCallback(() => {
    const origin = removalOrigin.current;
    controller.cancelRemoval();
    focusNextFrame(() => origin ?? trigger.current);
  }, [controller]);
  const toggled = useCallback(
    (open: boolean) => {
      if (open) {
        return;
      }
      setCreating(false);
      setName("");
      controller.dismiss();
    },
    [controller],
  );
  const rows = snapshot.views.map((view) => ({
    current: view === snapshot.current,
    name: view,
    removing: view === snapshot.removing,
  }));

  return {
    snapshot,
    name,
    canRemove: snapshot.views.length > 1,
    panel: panelFor(creating, snapshot.removing),
    createLabel: MUTATION_LABELS.create[snapshot.creating ? "busy" : "idle"],
    removeLabel: MUTATION_LABELS.remove[snapshot.deleting ? "busy" : "idle"],
    rows,
    refs: { confirmRemoval, input, menu, newView, trigger },
    actions: {
      beginCreate,
      beginRemoval,
      cancelCreate,
      cancelRemoval,
      choose,
      remove,
      setName,
      submitCreate,
      toggled,
    },
  };
};
