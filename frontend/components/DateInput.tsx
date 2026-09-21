"use client";

import { useRef } from "react";

function isoToDisplay(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return "";
  return `${m[3]}.${m[2]}.${m[1]}`;
}

/**
 * A native <input type="date"> renders its closed-state text - including
 * the MM/DD/YYYY vs DD/MM/YYYY segment order - from the browser/OS locale,
 * not the page's `lang` attribute or anything else the page controls.
 * There is no supported way to force it to show ДД.ММ.ГГГГ for a visitor
 * whose browser is set to English.
 *
 * This keeps a real native <input type="date"> - full native picker,
 * keyboard entry, and (via `name`) native <form> submission - but makes
 * it fully transparent and overlays our own formatted text on top, so
 * what's visible always reads ДД.ММ.ГГГГ regardless of locale. Clicking
 * anywhere on the field clicks straight through to the native input
 * beneath, which opens its picker as normal.
 */
export function DateInput({
  id,
  name,
  value,
  onChange,
  ariaLabel,
  className,
}: {
  id?: string;
  name?: string;
  value: string;
  onChange: (iso: string) => void;
  ariaLabel?: string;
  className?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);

  return (
    <span className={["date-input", className].filter(Boolean).join(" ")} onClick={() => ref.current?.showPicker?.()}>
      <span className="date-input-display" aria-hidden="true">
        {isoToDisplay(value) || "дд.мм.гггг"}
      </span>
      <input
        ref={ref}
        id={id}
        name={name}
        type="date"
        className="date-input-native"
        value={value}
        aria-label={ariaLabel}
        onChange={(e) => onChange(e.target.value)}
      />
    </span>
  );
}
