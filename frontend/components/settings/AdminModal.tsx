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
  headerActions,
  closeOnBackdropClick,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  /** The default width is too cramped for a form with its own inner grid
   * (BodyCarDialog's этапы rows, four columns wide) - opt into roughly
   * double via .admin-modal--wide instead of widening every modal. */
  wide?: boolean;
  /** Rendered top-right, next to the title (e.g. Planner's "Перейти к ЗН") -
   * optional so every other AdminModal caller is unaffected. */
  headerActions?: React.ReactNode;
  /** Closes on a click landing directly on the dialog's own backdrop/
   * padding area (not on any of its content) - opt-in, off by default,
   * since a form with unsaved input generally shouldn't lose it to a
   * stray click; a read-only panel (e.g. Planner's missed-calls list)
   * wants this. */
  closeOnBackdropClick?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={wide ? "admin-modal admin-modal--wide" : "admin-modal"}
      onClose={onClose}
      onClick={
        closeOnBackdropClick
          ? (e) => {
              // A click that bubbles up all the way to the <dialog> itself
              // (not stopped by any child content) landed on its own
              // backdrop/padding area - e.target is only the dialog element
              // in that case, never a descendant.
              if (e.target === ref.current) onClose();
            }
          : undefined
      }
    >
      <div className="admin-modal-header">
        <h3 className="admin-modal-title">{title}</h3>
        {headerActions}
      </div>
      {children}
    </dialog>
  );
}
