import type { IframeHTMLAttributes, RefCallback } from "react";

type TrustedFrameProps = Omit<IframeHTMLAttributes<HTMLIFrameElement>, "ref"> & {
  active?: boolean;
  frameRef: RefCallback<HTMLIFrameElement>;
};

export const TrustedFrame = ({ active = true, frameRef, ...attributes }: TrustedFrameProps) => (
  <>
    {/* Studio reads Marimo state from these trusted same-origin documents. */}
    {/* react-doctor-disable-next-line react-doctor/iframe-missing-sandbox */}
    <iframe
      ref={frameRef}
      {...attributes}
      allow="clipboard-read; clipboard-write"
      hidden={!active}
      inert={!active}
    />
  </>
);

export const PreviewFrame = ({ runtime, ...props }: TrustedFrameProps & { runtime: string }) => (
  <TrustedFrame {...props} data-preview-frame="" data-preview-runtime-frame={runtime} />
);
