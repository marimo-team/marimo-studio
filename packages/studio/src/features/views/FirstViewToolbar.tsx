import { PlusIcon } from "lucide-react";
import { useRef, useState } from "react";

import { CreateViewDialog, type CreateViewDialogProps } from "./CreateViewDialog.tsx";

export const FirstViewToolbar = ({
  dialog,
  onOpen,
}: {
  dialog: Omit<CreateViewDialogProps, "open" | "onCancel" | "firstView">;
  onOpen: () => void;
}) => {
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  return (
    <header className="studio-toolbar" aria-label="Studio">
      <button
        ref={trigger}
        type="button"
        className="studio-control studio-menu-trigger studio-first-view"
        aria-haspopup="dialog"
        onClick={() => {
          setOpen(true);
          onOpen();
        }}
      >
        <PlusIcon className="studio-mode-icon" aria-hidden />
        <span>Add view</span>
      </button>
      <CreateViewDialog
        {...dialog}
        open={open}
        firstView
        onCancel={() => {
          setOpen(false);
          trigger.current?.focus();
        }}
      />
      {dialog.message && !open ? (
        <span className="studio-host-message" role="alert">
          {dialog.message.text}
        </span>
      ) : null}
      {dialog.busy ? <span role="status">Opening view</span> : null}
    </header>
  );
};
