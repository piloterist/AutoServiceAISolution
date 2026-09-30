"use client";

// A real automotive-style gauge: a ~215° arc dial with a chrome bezel, a
// recessed light dial face, numbers around the whole scale (not just the
// two ends), and a needle that sweeps in on mount. A translucent "trail"
// arc runs from the scale's minimum up to the needle's current position,
// colored red (low) fading to a deep green (near the target) - a progress
// indicator layered under the plain scale, not a separate decorative ring.
// See app/dashboard/page.tsx for the current use (Кузовной/Каховка's
// revenue load against its "В ноль"/"Цель" targets).

import { Exo_2 } from "next/font/google";
import { useEffect, useState } from "react";

const exo2 = Exo_2({ subsets: ["latin", "cyrillic"], weight: ["500", "600", "700", "800"] });

// Compass-style angles (0deg = up, clockwise). The gap (360 - SWEEP_DEG)
// sits centered on "straight down" (180deg); MIN_ANGLE is where that gap
// ends going clockwise (lower-left), and the arc then sweeps clockwise the
// long way - through left, up, right - to MAX_ANGLE (lower-right, one full
// SWEEP_DEG later, past 360deg, which sin/cos handle fine since they're
// periodic). 215deg total leaves a 145deg gap at the bottom, the classic
// speedometer silhouette - swap this pair and the arc opens at the TOP.
const SWEEP_DEG = 215;
const GAP_HALF_DEG = (360 - SWEEP_DEG) / 2;
const MIN_ANGLE = 180 + GAP_HALF_DEG;
const MAX_ANGLE = MIN_ANGLE + SWEEP_DEG;

// viewBox is 340 wide x 235 tall; the pivot sits above center so there's
// room below it for the recessed center readout and the unit caption. The
// bezel is deliberately taller than the viewBox (clipped top/bottom) - the
// arc's own 145deg bottom gap has nothing to show there anyway, so it
// reads as a bezel crop, not a mistake.
const CX = 170;
const CY = 150;
const BEZEL_R = 148;
const RING_R = 138;
const FACE_R = 126;
const TICK_MAJOR_OUTER = 120;
const TICK_MAJOR_INNER = 104;
const TICK_MINOR_OUTER = 116;
const TICK_MINOR_INNER = 108;
const NUMBER_R = 90;
const NEEDLE_LEN = 110;
const INNER_DISC_R = 58;
const MAJOR_COUNT = 6;
const MINOR_COUNT = 41;

function toRad(deg: number): number {
  return (deg * Math.PI) / 180;
}

/** Compass angle (0deg = up, clockwise) -> a point on the circle of radius
 * `r` centered on the gauge's pivot. */
function pointAt(angleDeg: number, r: number): { x: number; y: number } {
  const rad = toRad(angleDeg);
  return { x: CX + r * Math.sin(rad), y: CY - r * Math.cos(rad) };
}

function arcPath(angleFrom: number, angleTo: number, r: number): string {
  const from = pointAt(angleFrom, r);
  const to = pointAt(angleTo, r);
  const largeArc = angleTo - angleFrom > 180 ? 1 : 0;
  return `M ${from.x.toFixed(2)} ${from.y.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${to.x.toFixed(2)} ${to.y.toFixed(2)}`;
}

/** Compact ru-RU number for the dial's numbers and center readout - "8,8"
 * for 8 800 000, not "8,8М" (the "млн. руб." caption under the dial says
 * the unit once, instead of repeating a letter at every tick). Falls back
 * to the plain grouped form under a million. */
function formatCompact(value: number): string {
  if (Math.abs(value) >= 1_000_000) {
    return (value / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 });
  }
  return Math.round(value).toLocaleString("ru-RU");
}

export function GaugeChart({
  title,
  value,
  min,
  max,
}: {
  title: string;
  /** Current fact - can fall outside [min, max]; the needle pins at
   * whichever end it overshoots, same as a real gauge, but the digital
   * readout still shows the real number/percentage. */
  value: number;
  min: number;
  max: number;
}) {
  const [swept, setSwept] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setSwept(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  const span = max - min || 1;
  const rawFraction = (value - min) / span;
  const clampedFraction = Math.min(1, Math.max(0, rawFraction));
  const needleAngle = MIN_ANGLE + clampedFraction * SWEEP_DEG;
  const restAngle = MIN_ANGLE;
  const pct = rawFraction * 100;

  // Drawn once pointing straight up (compass 0deg) in its own local
  // coordinates, then rotated into place with a CSS `transform` on the
  // wrapping <g> - that's what lets the sweep-in actually animate (React
  // re-rendering different polygon `points` on every frame would just
  // snap, never interpolate; rotating a fixed shape via CSS transitions
  // cleanly).
  const needleTipLocal = pointAt(0, NEEDLE_LEN);
  const needleBackLocal = pointAt(180, 18);
  const needleLeftLocal = pointAt(-90, 5);
  const needleRightLocal = pointAt(90, 5);
  const needleRotation = swept ? needleAngle : restAngle;

  const majorTicks = Array.from({ length: MAJOR_COUNT }, (_, i) => MIN_ANGLE + (i / (MAJOR_COUNT - 1)) * SWEEP_DEG);
  const minorTicks = Array.from({ length: MINOR_COUNT }, (_, i) => MIN_ANGLE + (i / (MINOR_COUNT - 1)) * SWEEP_DEG).filter(
    (a) => !majorTicks.some((m) => Math.abs(m - a) < 0.01),
  );

  const gaugeId = "gauge-" + title.replace(/[^a-zA-Zа-яА-Я0-9]/g, "");

  // The trail's endpoint - min position while resting, the needle's own
  // (clamped) position once swept. Its `d` can't smoothly interpolate like
  // a CSS transform (path data doesn't tween), so it fades in via opacity
  // instead, timed just behind the needle's own sweep.
  const trailToAngle = swept ? needleAngle : MIN_ANGLE;

  // The trail gradient's stops are anchored to the MIN..MAX points in
  // absolute space (gradientUnits="userSpaceOnUse"), not to the trail
  // path's own (shorter) extent - so a color along the trail always
  // reflects that point's real position on the full scale (red at the very
  // bottom out near "В ноль", progressively deeper green approaching
  // "Цель"), rather than being re-stretched across whatever fraction the
  // needle currently reaches.
  const gradientFrom = pointAt(MIN_ANGLE, RING_R);
  const gradientTo = pointAt(MAX_ANGLE, RING_R);

  return (
    <div className="gauge-card" style={{ fontFamily: exo2.style.fontFamily }}>
      <div className="gauge-card-title">{title}</div>
      <svg viewBox="0 0 340 235" className="gauge-svg" role="img" aria-label={`${title}: ${pct.toFixed(0)}%`}>
        <defs>
          <linearGradient id={`${gaugeId}-bezel`} x1="20%" y1="0%" x2="80%" y2="100%">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="45%" stopColor="#d8dee8" />
            <stop offset="100%" stopColor="#aab2c0" />
          </linearGradient>
          <radialGradient id={`${gaugeId}-face`} cx="50%" cy="38%" r="70%">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="70%" stopColor="#f3f5f9" />
            <stop offset="100%" stopColor="#e4e8f0" />
          </radialGradient>
          <radialGradient id={`${gaugeId}-inner`} cx="50%" cy="35%" r="75%">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="100%" stopColor="#e7ebf2" />
          </radialGradient>
          {/* Red (at "В ноль") -> amber -> a progressively deeper green
              (approaching "Цель"). userSpaceOnUse + explicit x1/y1/x2/y2 so
              this maps to ABSOLUTE position on the dial, not to the
              trail's own shorter length - see the comment above. */}
          <linearGradient
            id={`${gaugeId}-trail`}
            gradientUnits="userSpaceOnUse"
            x1={gradientFrom.x}
            y1={gradientFrom.y}
            x2={gradientTo.x}
            y2={gradientTo.y}
          >
            <stop offset="0%" stopColor="#ef4444" />
            <stop offset="45%" stopColor="#f59e0b" />
            <stop offset="75%" stopColor="#22c55e" />
            <stop offset="100%" stopColor="#15803d" />
          </linearGradient>
          <linearGradient id={`${gaugeId}-needle`} x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#ff8a4c" />
            <stop offset="100%" stopColor="#e8402f" />
          </linearGradient>
          <filter id={`${gaugeId}-soft`} x="-60%" y="-60%" width="220%" height="220%">
            <feDropShadow dx="0" dy="1.5" stdDeviation="2" floodColor="#1b2333" floodOpacity="0.28" />
          </filter>
        </defs>

        {/* Chrome bezel */}
        <circle cx={CX} cy={CY} r={BEZEL_R} fill={`url(#${gaugeId}-bezel)`} filter={`url(#${gaugeId}-soft)`} />

        {/* Plain scale ring (the full min..max span), with the translucent
            progress trail (min..current value) layered on top - only the
            trail carries color, so a glance shows both the whole range and
            how far into it the current reading is. */}
        <path d={arcPath(MIN_ANGLE, MAX_ANGLE, RING_R)} fill="none" stroke="#d7dce6" strokeWidth={4} strokeLinecap="round" />
        <path
          d={arcPath(MIN_ANGLE, trailToAngle, RING_R)}
          fill="none"
          stroke={`url(#${gaugeId}-trail)`}
          strokeWidth={11}
          strokeLinecap="round"
          opacity={swept ? 0.3 : 0}
          style={{ transition: "opacity 1.1s cubic-bezier(0.22, 1, 0.36, 1) 0.15s" }}
        />

        {/* Recessed white dial face */}
        <circle cx={CX} cy={CY} r={FACE_R} fill={`url(#${gaugeId}-face)`} stroke="#c7ccd6" strokeWidth={1} />

        {/* Minor ticks */}
        {minorTicks.map((angle, i) => {
          const p1 = pointAt(angle, TICK_MINOR_OUTER);
          const p2 = pointAt(angle, TICK_MINOR_INNER);
          return <line key={`minor-${i}`} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke="#b7bfcc" strokeWidth={1} />;
        })}

        {/* Major ticks + numbers around the whole scale */}
        {majorTicks.map((angle, i) => {
          const p1 = pointAt(angle, TICK_MAJOR_OUTER);
          const p2 = pointAt(angle, TICK_MAJOR_INNER);
          const numPos = pointAt(angle, NUMBER_R);
          const tickValue = min + (i / (MAJOR_COUNT - 1)) * span;
          const isEnd = i === 0 || i === MAJOR_COUNT - 1;
          return (
            <g key={`major-${i}`}>
              <line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke="#4a5468" strokeWidth={2.4} strokeLinecap="round" />
              <text x={numPos.x} y={numPos.y} textAnchor="middle" dominantBaseline="middle" className={isEnd ? "gauge-number gauge-number-end" : "gauge-number"}>
                {formatCompact(tickValue)}
              </text>
            </g>
          );
        })}

        {/* Needle - fixed shape pointing straight up, rotated into place via
            CSS transform so the sweep-in actually transitions smoothly
            (changing polygon `points` every frame would just snap, never
            interpolate). A short tail balances the long tapered tip, like a
            real needle pinned through its pivot. */}
        <g
          filter={`url(#${gaugeId}-soft)`}
          style={{
            transformOrigin: `${CX}px ${CY}px`,
            transform: `rotate(${needleRotation}deg)`,
            transition: "transform 1.1s cubic-bezier(0.22, 1, 0.36, 1)",
          }}
        >
          <polygon
            points={`${needleTipLocal.x.toFixed(2)},${needleTipLocal.y.toFixed(2)} ${needleLeftLocal.x.toFixed(2)},${needleLeftLocal.y.toFixed(2)} ${needleBackLocal.x.toFixed(2)},${needleBackLocal.y.toFixed(2)} ${needleRightLocal.x.toFixed(2)},${needleRightLocal.y.toFixed(2)}`}
            fill={`url(#${gaugeId}-needle)`}
          />
        </g>

        {/* Recessed center readout - value, then a smaller percentage below
            it, no unit letter (the "млн. руб." caption under the dial
            covers it once for the whole scale). This disc is drawn after
            the needle, so it also serves as the pivot's cap - no separate
            hub/dot needed. */}
        <circle cx={CX} cy={CY} r={INNER_DISC_R} fill={`url(#${gaugeId}-inner)`} stroke="#d3d8e2" strokeWidth={1} />
        <text x={CX} y={CY + 20} textAnchor="middle" className="gauge-readout-value">
          {formatCompact(value)}
        </text>
        <text x={CX} y={CY + 38} textAnchor="middle" className="gauge-readout-pct">
          {pct.toFixed(0)}%
        </text>

        {/* Unit caption under the whole dial, in the arc's own bottom gap. */}
        <text x={CX} y={CY + 66} textAnchor="middle" className="gauge-unit-label">
          млн. руб.
        </text>
      </svg>
    </div>
  );
}
