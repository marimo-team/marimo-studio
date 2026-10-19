import { InfoIcon } from "lucide-react";
import { useCallback, useEffect, useId, useRef } from "react";

const GAP = 8;
const POPOVER_SUPPORTED = "showPopover" in HTMLElement.prototype;

const place = (tip: HTMLElement, trigger: HTMLElement): void => {
  const anchor = trigger.getBoundingClientRect();
  const bubble = tip.getBoundingClientRect();
  const above = anchor.top - bubble.height - GAP;
  const top = above >= GAP ? above : anchor.bottom + GAP;
  const centered = anchor.left + anchor.width / 2 - bubble.width / 2;
  const left = Math.max(GAP, Math.min(centered, globalThis.innerWidth - bubble.width - GAP));
  tip.style.setProperty("--studio-help-top", `${top}px`);
  tip.style.setProperty("--studio-help-left", `${left}px`);
};

const isOpen = (tip: HTMLElement | null): boolean =>
  POPOVER_SUPPORTED && tip?.matches(":popover-open") === true;

/**
 * Explain the control beside it. The text shows on mouse hover and keyboard
 * focus, and also serves as the control's accessible description through `id`.
 */
export const HelpTip = ({ id, label, text }: { id?: string; label: string; text: string }) => {
  const generated = useId();
  const tipId = id ?? generated;
  const trigger = useRef<HTMLButtonElement>(null);
  const tip = useRef<HTMLSpanElement>(null);
  const hide = useCallback(() => {
    const element = tip.current;
    if (element && isOpen(element)) {
      element.hidePopover();
    }
  }, []);
  const show = useCallback(() => {
    const element = tip.current;
    const anchor = trigger.current;
    if (!POPOVER_SUPPORTED || !element || !anchor || isOpen(element)) {
      return;
    }
    element.showPopover();
    place(element, anchor);
  }, []);

  // The tip sits at fixed coordinates, so moving the content beneath it hides it.
  useEffect(() => {
    globalThis.addEventListener("scroll", hide, true);
    globalThis.addEventListener("resize", hide);
    return () => {
      globalThis.removeEventListener("scroll", hide, true);
      globalThis.removeEventListener("resize", hide);
    };
  }, [hide]);

  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="studio-help-trigger"
        aria-label={`About ${label}`}
        aria-describedby={tipId}
        // A tap focuses the trigger, which shows the tip until focus moves on,
        // so only a mouse pointer shows and hides it by hovering.
        onPointerEnter={(event) => event.pointerType === "mouse" && show()}
        onPointerLeave={(event) => event.pointerType === "mouse" && hide()}
        onFocus={show}
        onBlur={hide}
        onKeyDown={(event) => {
          if (event.key === "Escape" && isOpen(tip.current)) {
            event.stopPropagation();
            event.preventDefault();
            hide();
          }
        }}
      >
        <InfoIcon aria-hidden="true" />
      </button>
      <span
        ref={tip}
        id={tipId}
        role="tooltip"
        className="studio-help-tip"
        popover="manual"
        hidden={!POPOVER_SUPPORTED}
      >
        {text}
      </span>
    </>
  );
};
