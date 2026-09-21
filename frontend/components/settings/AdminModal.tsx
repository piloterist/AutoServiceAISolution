"use client";

import { useEffect, useRef } from "react";

/** Thin wrapper around the native <dialog> for the Settings admin CRUD
 * forms - gets backdrop/ESC-to-close/focus-trap for free, same choice the
 * Planner design reference makes for its own dialogs. */
export function AdminModal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog ref={ref} className="admin-modal" onClose={onClose}>
      <h3 className="admin-modal-title">{title}</h3>
      {children}
    </dialog>
  );
}
