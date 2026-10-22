"use client";

import { useEffect, useRef, useState } from "react";

/** A labeled dropdown of checkboxes for picking several values out of a
 * list - originally built for WorkOrdersTable's own Статус/Оплата/Вид
 * ремонта filters, extracted (product ask, 2026-10-23) so Settings ->
 * Общие's "Гарантийные" multi-select could reuse it instead of a bare
 * flat list of checkboxes, which doesn't scale once there are many
 * options. */
export function MultiSelectDropdown({
  label,
  options,
  selected,
  onToggle,
  onClear,
  emptyMessage,
}: {
  label: string;
  options: string[];
  selected: string[];
  onToggle: (value: string) => void;
  onClear: () => void;
  emptyMessage: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDetailsElement>(null);

  // A native <details> only closes on a second click on its own <summary>
  // - it has no built-in "click outside to close" behavior the way a
  // <select> dropdown does. Made controlled so an outside click can close
  // it too, without interfering with clicking the summary itself (native
  // toggle) or checking boxes inside the panel (both are inside `ref`, so
  // the outside-click check leaves them alone).
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  const summaryText =
    selected.length === 0
      ? "Все"
      : selected.length <= 2
        ? selected.join(", ")
        : `Выбрано: ${selected.length}`;

  return (
    <div className="dropdown-filter">
      <span className="period-filter-label">{label}</span>
      <details
        ref={ref}
        className="status-filter"
        open={open}
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
        <summary>{summaryText}</summary>
        <div className="status-filter-panel">
          {options.length === 0 && <p className="status-filter-empty">{emptyMessage}</p>}
          {options.map((option) => (
            <label key={option} className="status-filter-checkbox">
              <input
                type="checkbox"
                checked={selected.includes(option)}
                onChange={() => onToggle(option)}
              />
              {option}
            </label>
          ))}
          {selected.length > 0 && (
            <button type="button" className="status-filter-clear" onClick={onClear}>
              Сбросить
            </button>
          )}
        </div>
      </details>
    </div>
  );
}
