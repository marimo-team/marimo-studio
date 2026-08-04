import { useCallback, useState } from "react";

export const useDisclosure = (initial = false) => {
  const [open, setOpen] = useState(initial);
  const show = useCallback(() => setOpen(true), []);
  const hide = useCallback(() => setOpen(false), []);
  const toggle = useCallback(() => setOpen((current) => !current), []);
  return { hide, open, show, toggle };
};
