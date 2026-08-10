import { useLayoutEffect, useRef } from "react";

export const useLatest = <T>(value: T) => {
  const reference = useRef(value);
  useLayoutEffect(() => {
    reference.current = value;
  }, [value]);
  return reference;
};
