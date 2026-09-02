import { type IframeHTMLAttributes, type RefCallback, useLayoutEffect, useRef } from "react";

import type { Rectangle } from "./model.ts";

type TrustedFrameProps = Omit<IframeHTMLAttributes<HTMLIFrameElement>, "ref" | "title"> & {
  active?: boolean;
  frameRef: RefCallback<HTMLIFrameElement>;
  interactive?: boolean;
  title: string;
};

export const TrustedFrame = ({
  active = true,
  frameRef,
  interactive = active,
  title,
  ...attributes
}: TrustedFrameProps) => (
  <>
    {/* Editor frames share Marimo's origin. PreviewFrame supplies its sandbox. */}
    {/* react-doctor-disable-next-line react-doctor/iframe-missing-sandbox */}
    <iframe
      ref={frameRef}
      {...attributes}
      title={title}
      allow="clipboard-write"
      aria-busy={active && !interactive ? true : undefined}
      hidden={!active}
      inert={!active || !interactive}
    />
  </>
);

export const PreviewFrame = ({
  primary = true,
  runtime,
  view,
  ...props
}: TrustedFrameProps & { primary?: boolean; runtime: string; view?: string }) => (
  <TrustedFrame
    {...props}
    data-preview-frame=""
    data-preview-cache-runtime={runtime}
    data-preview-runtime-frame={primary ? runtime : undefined}
    data-preview-view-frame={view}
    sandbox="allow-downloads allow-forms allow-modals allow-pointer-lock allow-popups allow-scripts"
  />
);

export const PositionedEditorFrame = ({
  frame,
  measured,
  placement,
}: {
  frame: HTMLIFrameElement;
  measured: boolean;
  placement?: Rectangle;
}) => {
  const mount = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const target = mount.current;
    const host = frame.parentElement;
    if (!target || !host) {
      return;
    }
    const position = () => {
      if (!measured) {
        return;
      }
      const focused =
        document.activeElement === frame
          ? frame.contentDocument?.querySelector<HTMLElement>(":focus")
          : undefined;
      const rectangle = target.getBoundingClientRect();
      host.hidden = placement === undefined;
      if (placement === undefined) {
        return;
      }
      host.style.inset = "auto";
      host.style.left = `${rectangle.left}px`;
      host.style.top = `${rectangle.top}px`;
      host.style.width = `${rectangle.width}px`;
      host.style.height = `${rectangle.height}px`;
      focused?.focus({ preventScroll: true });
    };
    position();
    const observer = new ResizeObserver(position);
    observer.observe(target);
    globalThis.addEventListener("resize", position);
    return () => {
      observer.disconnect();
      globalThis.removeEventListener("resize", position);
      host.hidden = false;
      host.style.inset = "0";
      host.style.removeProperty("left");
      host.style.removeProperty("top");
      host.style.removeProperty("width");
      host.style.removeProperty("height");
    };
  }, [frame, measured, placement]);

  return <div ref={mount} className="studio-editor-frame-mount" />;
};
