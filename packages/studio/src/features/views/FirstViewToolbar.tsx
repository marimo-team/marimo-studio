import { PlusIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useDisclosureMenu } from "../../shared/useDisclosureMenu.ts";
import { CreateViewForm, type CreateViewFormProps } from "./CreateViewForm.tsx";

export const FirstViewToolbar = ({
  form,
  onOpen,
}: {
  form: Omit<CreateViewFormProps, "inputRef" | "onCancel">;
  onOpen: () => void;
}) => {
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const menu = useDisclosureMenu({
    dismissible: !form.busy,
    onToggle: (visible) => {
      setOpen(visible);
      if (visible) onOpen();
    },
  });
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);
  return (
    <header className="studio-toolbar" aria-label="Studio">
      <details
        ref={menu.detailsRef}
        className="studio-menu studio-view-menu studio-first-view"
        data-studio-disclosure-menu
        onToggle={menu.onToggle}
        onKeyDown={menu.onKeyDown}
      >
        <summary ref={menu.triggerRef} className="studio-control studio-menu-trigger">
          <PlusIcon className="studio-mode-icon" aria-hidden />
          <span>Add view</span>
        </summary>
        <div className="studio-menu-popover">
          {open ? <CreateViewForm {...form} inputRef={input} onCancel={menu.close} /> : null}
        </div>
      </details>
      {form.message && !open ? (
        <span className="studio-host-message" role="alert">
          {form.message.text}
        </span>
      ) : null}
      {form.busy ? <span role="status">Opening view</span> : null}
    </header>
  );
};
