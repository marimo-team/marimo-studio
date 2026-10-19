import { InfoIcon } from "lucide-react";
import { useCallback, useId, useRef } from "react";

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

/**
 * Explain the control beside it. The text shows on hover and keyboard focus,
 * and also serves as the control's accessible description through `id`.
 */
export const HelpTip = ({ id, label, text }: { id?: string; label: string; text: string }) => {
  const generated = useId();
  const tipId = id ?? generated;
  const trigger = useRef<HTMLButtonElement>(null);
  const tip = useRef<HTMLSpanElement>(null);
  const show = useCallback(() => {
    const element = tip.current;
    const anchor = trigger.current;
    if (!POPOVER_SUPPORTED || !element || !anchor || element.matches(":popover-open")) {
      return;
    }
    element.showPopover();
    place(element, anchor);
  }, []);
  const hide = useCallback(() => {
    if (POPOVER_SUPPORTED && tip.current?.matches(":popover-open")) {
      tip.current.hidePopover();
    }
  }, []);
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="studio-help-trigger"
        aria-label={`About ${label}`}
        aria-describedby={tipId}
        onPointerEnter={show}
        onPointerLeave={hide}
        onFocus={show}
        onBlur={hide}
        onKeyDown={(event) => {
          if (event.key === "Escape" && tip.current?.matches(":popover-open")) {
            event.stopPropagation();
            event.preventDefault();
            hide();
          }
        }}
      >
        <InfoIcon aria-hidden="true" />
      </button>
      <span ref={tip} id={tipId} role="tooltip" className="studio-help-tip" popover="manual">
        {text}
      </span>
    </>
  );
};
