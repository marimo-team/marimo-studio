// @deno-types="npm:@types/react@19.2.10"
import type { HTMLAttributes as _HTMLAttributes } from "react";

declare module "react" {
  interface HTMLAttributes<T> {
    "mo-value"?: string;
  }

  namespace JSX {
    interface IntrinsicElements {
      "marimo-cell": _HTMLAttributes<HTMLElement> & { name: string };
      "marimo-output": _HTMLAttributes<HTMLElement> & { value: string };
    }
  }
}
