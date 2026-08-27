// @deno-types="npm:@types/react@19.2.10"
import { useEffect, useRef, useState } from "react";

export type MarimoValueElement<T> = HTMLSpanElement & {
  marimoValue?: T;
};

export const useMarimoValue = <T>(selector: string) => {
  const hostRef = useRef<MarimoValueElement<T>>(null);
  const [value, setValue] = useState<T>();
  const [error, setError] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (host === null) {
      return;
    }

    const sync = () => {
      setValue(host.marimoValue);
      setError(false);
    };
    const fail = () => setError(true);

    host.addEventListener("marimo-value-updated", sync);
    host.addEventListener("marimo-value-error", fail);
    sync();

    return () => {
      host.removeEventListener("marimo-value-updated", sync);
      host.removeEventListener("marimo-value-error", fail);
    };
  }, [selector]);

  return { error, hostRef, value };
};
