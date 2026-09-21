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
  wide,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  /** The default width is too cramped for a form with its own inner grid
   * (BodyCarDialog's этапы rows, four columns wide) - opt into roughly
   * double via .admin-modal--wide instead of widening every modal. */
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog ref={ref} className={wide ? "admin-modal admin-modal--wide" : "admin-modal"} onClose={onClose}>
      <h3 className="admin-modal-title">{title}</h3>
      {children}
    </dialog>
  );
}
