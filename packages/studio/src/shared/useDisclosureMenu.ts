import {
  type KeyboardEvent,
  type RefObject,
  type SyntheticEvent,
  useCallback,
  useEffect,
  useRef,
} from "react";

import { registerDisclosureMenu, requestDisclosureMenuOpen } from "./disclosureMenuCoordinator.ts";

const pendingFocusRestoration = new WeakMap<HTMLDetailsElement, boolean>();

const closeDisclosureMenu = (menu: HTMLDetailsElement, restoreFocus: boolean): void => {
  if (!menu.open) {
    return;
  }
  pendingFocusRestoration.set(menu, restoreFocus);
  menu.removeAttribute("open");
};

const menuTrigger = (menu: HTMLDetailsElement): HTMLElement | null => {
  const trigger = menu.firstElementChild;
  return trigger instanceof HTMLElement && trigger.tagName === "SUMMARY" ? trigger : null;
};

interface DisclosureMenuOptions {
  detailsRef?: RefObject<HTMLDetailsElement | null>;
  dismissible?: boolean;
  onToggle?: (open: boolean) => void;
  triggerRef?: RefObject<HTMLElement | null>;
}

export const useDisclosureMenu = ({
  detailsRef,
  dismissible = true,
  onToggle,
  triggerRef,
}: DisclosureMenuOptions = {}) => {
  const ownedDetailsRef = useRef<HTMLDetailsElement>(null);
  const ownedTriggerRef = useRef<HTMLElement>(null);
  const menuRef = detailsRef ?? ownedDetailsRef;
  const summaryRef = triggerRef ?? ownedTriggerRef;
  const dismissibleRef = useRef(dismissible);
  dismissibleRef.current = dismissible;

  const focusTrigger = useCallback(() => {
    const menu = menuRef.current;
    const trigger = summaryRef.current ?? (menu ? menuTrigger(menu) : null);
    if (menu && !menu.open) {
      trigger?.focus();
    }
  }, [menuRef, summaryRef]);

  const close = useCallback(() => {
    const menu = menuRef.current;
    if (!menu || !dismissible) {
      return;
    }
    closeDisclosureMenu(menu, true);
    focusTrigger();
  }, [dismissible, focusTrigger, menuRef]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDetailsElement>) => {
      if (event.key !== "Escape" || !event.currentTarget.open || !dismissible) {
        return;
      }
      event.preventDefault();
      close();
    },
    [close, dismissible],
  );

  const handleToggle = useCallback(
    (event: SyntheticEvent<HTMLDetailsElement>) => {
      const menu = event.currentTarget;
      onToggle?.(menu.open);
      if (menu.open) {
        pendingFocusRestoration.delete(menu);
        if (!requestDisclosureMenuOpen(menu)) {
          closeDisclosureMenu(menu, false);
        }
        return;
      }

      const restoreFocus = pendingFocusRestoration.get(menu);
      pendingFocusRestoration.delete(menu);
      if (
        restoreFocus === true ||
        (restoreFocus === undefined && menu.contains(menu.ownerDocument.activeElement))
      ) {
        focusTrigger();
      }
    },
    [focusTrigger, onToggle],
  );

  useEffect(() => {
    const menu = menuRef.current;
    if (!menu) {
      return;
    }
    return registerDisclosureMenu({
      canClose: () => dismissibleRef.current,
      close: () => closeDisclosureMenu(menu, false),
      menu,
    });
  }, [menuRef]);

  useEffect(() => {
    const lightDismiss = (event: PointerEvent) => {
      const menu = menuRef.current;
      if (
        !menu?.open ||
        !dismissible ||
        !(event.target instanceof Node) ||
        menu.contains(event.target)
      ) {
        return;
      }
      closeDisclosureMenu(menu, false);
    };
    document.addEventListener("pointerdown", lightDismiss);
    return () => document.removeEventListener("pointerdown", lightDismiss);
  }, [dismissible, menuRef]);

  return {
    detailsRef: menuRef,
    onKeyDown: handleKeyDown,
    onToggle: handleToggle,
    triggerRef: summaryRef,
  };
};
