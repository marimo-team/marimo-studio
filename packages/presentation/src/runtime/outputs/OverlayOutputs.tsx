import type { RenderedOutput } from "@marimo-studio/protocol/output-read";

import {
  isOutputMounted,
  ProjectedOutputArea,
  reconcileProjectedOutput,
} from "@marimo-studio/marimo-frontend/projected-output";
import { useEffect, useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";

const OverlayOutput = ({ output }: { output: RenderedOutput }) => {
  useLayoutEffect(() => reconcileProjectedOutput(output), [output]);
  return (
    <ProjectedOutputArea
      output={output}
      stale={false}
      functionRequestScope={{
        activeOwner: String(output.timestamp),
        outputOwner: String(output.timestamp),
      }}
    />
  );
};

export const OverlayOutputs = ({ outputs }: { outputs: RenderedOutput[] }) => {
  const [mounted, setMounted] = useState<ReadonlySet<string>>(new Set());
  useEffect(() => {
    const sync = () => {
      const shell = document.querySelector("#app-shell");
      const next = new Set<string>();
      for (const output of outputs) {
        if (shell && output.mimetype === "text/html" && isOutputMounted(output.data, shell))
          next.add(output.ownerCellId);
      }
      setMounted((current) =>
        current.size === next.size && [...current].every((id) => next.has(id)) ? current : next,
      );
    };
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [outputs]);
  return createPortal(
    <div data-marimo-studio-overlays="">
      {outputs.map((output) =>
        mounted.has(output.ownerCellId) ? null : (
          <OverlayOutput key={output.ownerCellId} output={output} />
        ),
      )}
    </div>,
    document.body,
  );
};
