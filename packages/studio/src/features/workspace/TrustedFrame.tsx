import type { IframeHTMLAttributes, RefCallback } from "react";

type TrustedFrameProps = Omit<IframeHTMLAttributes<HTMLIFrameElement>, "ref" | "title"> & {
  active?: boolean;
  frameRef: RefCallback<HTMLIFrameElement>;
  title: string;
};

export const TrustedFrame = ({
  active = true,
  frameRef,
  title,
  ...attributes
}: TrustedFrameProps) => (
  <>
    {/* Studio reads Marimo state from these trusted same-origin documents. */}
    {/* react-doctor-disable-next-line react-doctor/iframe-missing-sandbox */}
    <iframe
      ref={frameRef}
      {...attributes}
      title={title}
      allow="clipboard-read; clipboard-write"
      hidden={!active}
      inert={!active}
    />
  </>
);

export const PreviewFrame = ({ runtime, ...props }: TrustedFrameProps & { runtime: string }) => (
  <TrustedFrame {...props} data-preview-frame="" data-preview-runtime-frame={runtime} />
);
