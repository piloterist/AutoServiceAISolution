"use client";

// Compact trapezoid "mode" button (styled like a SPORT-mode switch, not a
// web toggle - see .cockpit-nzp-btn in globals.css) for blending НЗП into
// the revenue gauge. No visible label beyond "НЗП" itself - state reads
// from the glowing underline + text color, per product spec section 6.
export function NzpToggle({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      className="cockpit-nzp-btn"
      aria-pressed={active}
      aria-label="Включать НЗП"
      onClick={onToggle}
    >
      НЗП
    </button>
  );
}
