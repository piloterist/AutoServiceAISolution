// Pure geometry for the Cockpit's two arc gauges - kept separate from
// components/cockpit/InstrumentCluster.tsx so the angle math is trivially
// testable/reasoned-about on its own (see backend cockpit_service.py's own
// "раздели расчёт данных, расчёт геометрии и представление" split, mirrored
// here on the frontend for the one piece of geometry that lives client-side
// - the needle/tick angles; every money value itself stays a Decimal
// string until final render, see CockpitView.tsx).
//
// Angle convention: degrees clockwise from straight up (12 o'clock) - e.g.
// 90 = 3 o'clock (right), 180 = 6 o'clock (bottom), 270 = 9 o'clock (left).
// Both gauges are plain clockwise sweeps of a start/sweep pair in this one
// convention (no separate formula per gauge):
//   main (revenue): starts at 180 (bottom), sweeps 270 -> ends at 90
//     (right), leaving the bottom-right quadrant open, per the product
//     spec ("дуга примерно на 270°... нижняя правая четверть остаётся
//     свободной").
//   payments: starts at 150 (~5 o'clock), sweeps 270 -> ends at 60
//     (~2 o'clock), leaving roughly the right side open - the side the
//     main gauge overlaps it from anyway.

export type Point = { x: number; y: number };

export const MAIN_GAUGE_START_ANGLE = 180;
export const MAIN_GAUGE_SWEEP = 270;
export const PAYMENTS_GAUGE_START_ANGLE = 150;
export const PAYMENTS_GAUGE_SWEEP = 270;

// Rounded to a precision far below anything visible (a fraction of a
// pixel at this SVG's scale) - purely to fix a real hydration mismatch:
// Math.sin/Math.cos aren't required by spec to be bit-identical across JS
// engines, so Node (SSR) and the browser (client) can disagree in the
// last couple of float64 digits for the same angle, which React's
// hydration then flags as a real (if invisible) server/client mismatch.
function round(n: number): number {
  return Math.round(n * 1000) / 1000;
}

export function polarPoint(cx: number, cy: number, r: number, angleDeg: number): Point {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: round(cx + r * Math.sin(rad)), y: round(cy - r * Math.cos(rad)) };
}

export function clamp01(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

/** The angle (in this module's clockwise-from-12 convention) for a 0..1
 * position along a gauge's own start/sweep - used for both tick/label
 * placement (fraction = label value / max) and the needle (fraction =
 * needle_fraction from the backend, already clamped there). */
export function gaugeAngle(startAngle: number, sweep: number, fraction: number): number {
  return startAngle + sweep * clamp01(fraction);
}

/** SVG path `d` for a clockwise arc segment between two angles in this
 * module's convention - always sweeps forward (start -> end), never takes
 * the short way round, matching how every arc in this component is
 * defined (a start angle plus a forward sweep). */
export function arcPath(cx: number, cy: number, r: number, startAngle: number, endAngle: number): string {
  const sweep = endAngle - startAngle;
  const largeArc = ((sweep % 360) + 360) % 360 > 180 ? 1 : 0;
  const start = polarPoint(cx, cy, r, startAngle);
  const end = polarPoint(cx, cy, r, endAngle);
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 1 ${end.x} ${end.y}`;
}

/** One radial tick mark as a line segment from r1 to r2 at the given angle
 * - `d` attribute for a <path>, or use polarPoint twice directly for a
 * <line>. Kept as a path for a single consistent stroke API with arcPath. */
export function tickPath(cx: number, cy: number, r1: number, r2: number, angleDeg: number): string {
  const inner = polarPoint(cx, cy, r1, angleDeg);
  const outer = polarPoint(cx, cy, r2, angleDeg);
  return `M ${inner.x} ${inner.y} L ${outer.x} ${outer.y}`;
}

/** A filled ring segment ("donut slice") between two radii and two angles -
 * for an accent band the tick marks sit on top of as a background, rather
 * than a thin stroked line the ticks sit outside of. */
export function ringSegmentPath(
  cx: number,
  cy: number,
  innerR: number,
  outerR: number,
  startAngle: number,
  endAngle: number,
): string {
  const sweep = endAngle - startAngle;
  const largeArc = ((sweep % 360) + 360) % 360 > 180 ? 1 : 0;
  const outerStart = polarPoint(cx, cy, outerR, startAngle);
  const outerEnd = polarPoint(cx, cy, outerR, endAngle);
  const innerEnd = polarPoint(cx, cy, innerR, endAngle);
  const innerStart = polarPoint(cx, cy, innerR, startAngle);
  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${outerR} ${outerR} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${innerR} ${innerR} 0 ${largeArc} 0 ${innerStart.x} ${innerStart.y}`,
    "Z",
  ].join(" ");
}
