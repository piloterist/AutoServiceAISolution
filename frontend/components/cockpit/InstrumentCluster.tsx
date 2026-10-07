"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useRouter } from "next/navigation";

import { NzpToggle } from "@/components/cockpit/NzpToggle";
import {
  arcPath,
  gaugeAngle,
  MAIN_GAUGE_START_ANGLE,
  MAIN_GAUGE_SWEEP,
  PAYMENTS_GAUGE_START_ANGLE,
  PAYMENTS_GAUGE_SWEEP,
  polarPoint,
  ringSegmentPath,
  tickPath,
} from "@/lib/cockpit-geometry";
import type { GaugeReading, WorkshopOption } from "@/lib/backend-api";

const VIEW_W = 1648;
const VIEW_H = 650;

const MAIN = { cx: 887, cy: 329, r: 296 };
const PAY = { cx: 489, cy: 335, r: 185 };

function formatRub(value: number): string {
  return value.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Rubles -> millions, 2 decimals, Russian comma - e.g. 813217 -> "0,81".
function formatMillions(value: number): string {
  return (value / 1_000_000).toLocaleString("ru-RU", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function DialFace({
  id,
  cx,
  cy,
  r,
  vertical,
}: {
  id: string;
  cx: number;
  cy: number;
  r: number;
  vertical?: boolean;
}) {
  // Near-black carbon-weave texture - a fine crosshatch pattern, very low
  // contrast against the near-black face fill (see product spec: "почти
  // чёрная карбоновая фактура... с очень низкой контрастностью").
  const patternId = `${id}-carbon`;
  return (
    <>
      <defs>
        <pattern
          id={patternId}
          width={vertical ? 5 : 7}
          height={vertical ? 7 : 5}
          patternUnits="userSpaceOnUse"
          patternTransform={vertical ? "rotate(0)" : "rotate(0)"}
        >
          <rect width={vertical ? 5 : 7} height={vertical ? 7 : 5} fill="#0a0d0e" />
          <path
            d={vertical ? "M0,0 L5,0 M0,3.5 L5,3.5" : "M0,0 L0,5 M3.5,0 L3.5,5"}
            stroke="#141a1c"
            strokeWidth={1}
          />
        </pattern>
        <radialGradient id={`${id}-sheen`} cx="35%" cy="28%" r="75%">
          <stop offset="0%" stopColor="#22292b" stopOpacity={0.55} />
          <stop offset="35%" stopColor="#0d1112" stopOpacity={0.15} />
          <stop offset="100%" stopColor="#000000" stopOpacity={0} />
        </radialGradient>
      </defs>
      <circle cx={cx} cy={cy} r={r} fill={`url(#${patternId})`} />
      <circle cx={cx} cy={cy} r={r} fill={`url(#${id}-sheen)`} />
    </>
  );
}

function ChromeRing({ cx, cy, r, width, id }: { cx: number; cy: number; r: number; width: number; id: string }) {
  return (
    <>
      <defs>
        <linearGradient id={id} x1="20%" y1="0%" x2="80%" y2="100%">
          <stop offset="0%" stopColor="#3a4145" />
          <stop offset="22%" stopColor="#171b1d" />
          <stop offset="48%" stopColor="#596063" />
          <stop offset="62%" stopColor="#1a1e20" />
          <stop offset="100%" stopColor="#24292b" />
        </linearGradient>
      </defs>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={`url(#${id})`} strokeWidth={width} />
    </>
  );
}

/** A glowing accent band: a wide, blurred, dim halo underneath a slim,
 * bright, unblurred core on top - the standard way to fake a backlit/neon
 * line in SVG (per product feedback, matching the reference photo's own
 * glowing arcs). An earlier attempt used a radial gradient across the
 * stroke's own width instead, but that fought the gauge group's own
 * Gaussian-blur filter (id="cockpit-glow", applied around the whole
 * MainGauge/PaymentsGauge in InstrumentCluster below): blurring a stroke
 * whose opacity already peaks in the middle and fades at both edges smears
 * that peak into the (until then transparent) edges, visually flattening or
 * even inverting it - the "dark stripe down the middle" the gradient
 * version produced. Two plain strokes have no such interaction. */
function GlowBand({
  d,
  color,
  width,
  coreOpacity = 0.95,
  haloOpacity = 0.45,
}: {
  d: string;
  color: string;
  width: number;
  coreOpacity?: number;
  haloOpacity?: number;
}) {
  return (
    <>
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={width}
        strokeOpacity={haloOpacity}
        strokeLinecap="round"
        filter="url(#cockpit-band-blur)"
      />
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={Math.max(2, width * 0.35)}
        strokeOpacity={coreOpacity}
        strokeLinecap="round"
      />
    </>
  );
}

function Needle({
  cx,
  cy,
  length,
  angle,
  hubR,
  scale = 1,
  transitionMs,
}: {
  cx: number;
  cy: number;
  length: number;
  angle: number;
  hubR: number;
  scale?: number;
  // Overrides .cockpit-needle's own default CSS transition duration for
  // this render - used only during MainGauge's one-shot "прогазовка"
  // reveal (see there), which needs its first rise noticeably slower than
  // a normal data-driven needle movement.
  transitionMs?: number;
}) {
  const w = 10 * scale;
  const tailW = 7 * scale;
  const tail = 28 * scale;
  return (
    <g
      transform={`rotate(${angle} ${cx} ${cy})`}
      className="cockpit-needle"
      style={transitionMs !== undefined ? { transitionDuration: `${transitionMs}ms` } : undefined}
    >
      {/* Needle body: points "up" at rest (angle 0), rotated to its real
          reading via the SVG transform above - this module's angle
          convention (clockwise from 12 o'clock) is exactly SVG rotate()'s
          own, so no extra conversion is needed here. Bright red body (spec's
          #F3202D), white edge highlight, dark tail - see product spec
          section 4 ("красное тело, белым бликом вдоль края"). */}
      <path
        d={`M ${cx - w} ${cy} L ${cx - 2 * scale} ${cy - length} L ${cx + 2 * scale} ${cy - length} L ${cx + w} ${cy} L ${cx + tailW} ${cy + tail} L ${cx - tailW} ${cy + tail} Z`}
        fill="#f3202d"
        stroke="#1a0304"
        strokeWidth={1.5}
      />
      <path
        d={`M ${cx - 1.4 * scale} ${cy - 6} L ${cx - 0.8 * scale} ${cy - length + 5} L ${cx} ${cy - length} L ${cx + 0.7 * scale} ${cy - length + 7}`}
        fill="none"
        stroke="#ffffff"
        strokeWidth={1.6 * scale}
        strokeLinecap="round"
      />
      <circle cx={cx} cy={cy} r={hubR} fill="#0c0e0f" stroke="#596063" strokeWidth={2.5} />
      <circle cx={cx} cy={cy} r={hubR * 0.55} fill="none" stroke="#8a999e" strokeWidth={1} opacity={0.8} />
    </g>
  );
}

function PlanMarker({ cx, cy, r, angle }: { cx: number; cy: number; r: number; angle: number }) {
  const tip = polarPoint(cx, cy, r - 6, angle);
  const baseOuter = r + 10;
  const left = polarPoint(cx, cy, baseOuter, angle - 1.6);
  const right = polarPoint(cx, cy, baseOuter, angle + 1.6);
  return (
    <g className="cockpit-plan-marker" aria-hidden="true">
      <path
        d={`M ${tip.x} ${tip.y} L ${left.x} ${left.y} L ${right.x} ${right.y} Z`}
        fill="#eafcff"
        stroke="#3ebecc"
        strokeWidth={1}
      />
    </g>
  );
}

function MainGauge({
  revenue,
  effectiveRevenue,
  gauge,
  nzpActive,
  planUnusable,
  hasUnattributedRevenue,
}: {
  revenue: number;
  effectiveRevenue: number;
  gauge: GaugeReading;
  nzpActive: boolean;
  planUnusable: boolean;
  hasUnattributedRevenue: boolean;
}) {
  const id = useId();
  const { cx, cy, r } = MAIN;
  const faceR = r - 34;
  const tickOuter = r - 40;
  const tickInner = r - 58;
  const minorInner = r - 50;
  const labelR = r - 96;
  // The accent band is a filled ring the ticks sit on top of, not a thin
  // line they sit outside of - its outer edge sits just past the ticks
  // (anchored, solid, near the rim) and its inner edge fades toward the
  // dial's own center (see the radial gradients below) instead of glowing
  // symmetrically to both sides of a thin line. Kept narrow (half the
  // radial span of an earlier version, which read as too wide/dominant).
  const bandOuterR = tickOuter + 4;
  const bandInnerR = Math.max(20, bandOuterR - 60);
  const bandSolidFromPct = (tickInner / bandOuterR) * 100;
  const bandFadeToPct = (bandInnerR / bandOuterR) * 100;

  // A scale is always present (see backend cockpit_service.get_snapshot's
  // neutral-scale fallback) - ticks/numbers stay on the dial even without a
  // usable plan; only the plan-marker triangle is gated on planUnusable
  // (the last-two-intervals red zone is purely decorative, per product
  // spec, so it shows regardless of whether a real plan is set).
  const scale = gauge.scale;
  const needleAngle = gaugeAngle(MAIN_GAUGE_START_ANGLE, MAIN_GAUGE_SWEEP, gauge.needle_fraction);
  const endAngle = MAIN_GAUGE_START_ANGLE + MAIN_GAUGE_SWEEP;

  const displayValue = nzpActive ? effectiveRevenue : revenue;

  // "Прогазовка" reveal (per product feedback, 2026-09-30 - a reference to
  // how a combustion-engine tach blips on startup, refined twice the same
  // day: one slow rise from 0 to mid-red, a long hold there with a bit of
  // natural wobble rather than standing dead still, then settle on the
  // real reading - no second rise, no dip through blue). A one-shot
  // sequence of discrete angle jumps, each animated by .cockpit-needle's
  // own existing CSS transition mechanism (deliberately NOT a parallel CSS
  // keyframe animation on the needle's transform - see that class's
  // comment on why a second transform-origin/pivot source is a real bug
  // magnet here); the REVEAL_*_MS constants override that transition's
  // default duration for these jumps, via Needle's own transitionMs prop.
  // Same red-zone math as the red band below.
  const redStartFraction =
    scale.labels_millions.length > 2 ? Math.max(0, (scale.labels_millions.length - 3) / (scale.labels_millions.length - 1)) : 0;
  const redMidAngle = gaugeAngle(MAIN_GAUGE_START_ANGLE, MAIN_GAUGE_SWEEP, (redStartFraction + 1) / 2);
  // .cockpit-cluster fades in over 5.7s on an ease-out curve, which is
  // already ~50% opaque well before 1s in - starting the rise any earlier
  // makes it invisible (per product feedback: "не видно как она
  // поднимается от нуля... начинать чуть позже, когда прозрачность уже
  // достигнута процентов на 50").
  const REVEAL_RISE_START_MS = 1000;
  const REVEAL_RISE_MS = 1600;
  const REVEAL_HOLD_MS = 1400;
  const REVEAL_WOBBLE_STEP_MS = 260;
  const REVEAL_WOBBLE_MS = 200;
  const REVEAL_SETTLE_MS = 700;
  const [revealAngle, setRevealAngle] = useState(MAIN_GAUGE_START_ANGLE);
  const [revealDurationMs, setRevealDurationMs] = useState(REVEAL_RISE_MS);
  const [blipDone, setBlipDone] = useState(false);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setBlipDone(true);
      return;
    }
    const timers: ReturnType<typeof setTimeout>[] = [];
    const at = (delay: number, fn: () => void) => timers.push(setTimeout(fn, delay));

    at(REVEAL_RISE_START_MS, () => {
      setRevealDurationMs(REVEAL_RISE_MS);
      setRevealAngle(redMidAngle);
    });

    // A few small, quick nudges around mid-red instead of standing dead
    // still through the whole hold - per product feedback: "в красной
    // зоне пусть она немного меняет положение... а то выглядит не
    // натурально".
    const holdStart = REVEAL_RISE_START_MS + REVEAL_RISE_MS;
    for (let t = 0; t < REVEAL_HOLD_MS; t += REVEAL_WOBBLE_STEP_MS) {
      at(holdStart + t, () => {
        setRevealDurationMs(REVEAL_WOBBLE_MS);
        setRevealAngle(redMidAngle + (Math.random() - 0.5) * 12);
      });
    }

    const settleStart = holdStart + REVEAL_HOLD_MS;
    at(settleStart, () => {
      setRevealDurationMs(REVEAL_SETTLE_MS);
      setRevealAngle(needleAngle);
    });
    at(settleStart + REVEAL_SETTLE_MS, () => setBlipDone(true));

    return () => timers.forEach(clearTimeout);
    // Runs once on mount only, like .cockpit-cluster's own reveal fade -
    // later data/filter changes move the needle straight to its new real
    // angle via the normal CSS transition, never replaying the blip.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const displayAngle = blipDone ? needleAngle : revealAngle;

  // The money readout sits dead-center under the hub (x=cx), but early in
  // the sweep the needle's own long tip points almost straight down
  // through that exact spot, covering part of the sum - per product
  // feedback ("так бывает в начале месяца, когда цифра маленькая"). A
  // shift that faded in/out with the needle's own position made the sum
  // visibly hop left/right as it moved (per follow-up feedback: "не
  // нравится что скачет") - simpler and steadier to just always sit it off
  // to the right, clear of the needle in every position.
  const MONEY_SHIFT_PX = 90;
  const moneyOffsetStyle = { transform: `translateX(${MONEY_SHIFT_PX}px)` };

  return (
    <g aria-hidden="true">
      <ChromeRing cx={cx} cy={cy} r={r} width={14} id={`${id}-chrome-outer`} />
      <ChromeRing cx={cx} cy={cy} r={r - 15} width={6} id={`${id}-chrome-inner`} />
      <DialFace id={`${id}-face`} cx={cx} cy={cy} r={faceR} />

      {/* Background accent band the tick marks sit on top of - solid from
          the rim through the tick zone, then fading toward the dial's own
          center (per product feedback: "риски должны быть на синем фоне, а
          рассеивание - в сторону центра"), not a thin line glowing evenly
          to both sides. */}
      <defs>
        <radialGradient id={`${id}-band-cyan`} cx={cx} cy={cy} r={bandOuterR} gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#3ebecc" stopOpacity={0} />
          <stop offset={`${bandFadeToPct}%`} stopColor="#3ebecc" stopOpacity={0} />
          <stop offset={`${bandSolidFromPct}%`} stopColor="#3ebecc" stopOpacity={0.88} />
          <stop offset="100%" stopColor="#3ebecc" stopOpacity={0.95} />
        </radialGradient>
        <radialGradient id={`${id}-band-red`} cx={cx} cy={cy} r={bandOuterR} gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#f3202d" stopOpacity={0} />
          <stop offset={`${bandFadeToPct}%`} stopColor="#f3202d" stopOpacity={0} />
          <stop offset={`${bandSolidFromPct}%`} stopColor="#f3202d" stopOpacity={0.95} />
          <stop offset="100%" stopColor="#f3202d" stopOpacity={1} />
        </radialGradient>
      </defs>
      <path
        d={ringSegmentPath(cx, cy, bandInnerR, bandOuterR, MAIN_GAUGE_START_ANGLE, endAngle)}
        fill={`url(#${id}-band-cyan)`}
      />
      {/* Last two major intervals filled solid red - decorative accent, not
          a danger signal (per product spec, shown regardless of plan
          status), fully replacing the blue band in that stretch rather
          than just accenting it. */}
      {scale.labels_millions.length > 2 && (
        <path
          d={ringSegmentPath(
            cx,
            cy,
            bandInnerR,
            bandOuterR,
            gaugeAngle(
              MAIN_GAUGE_START_ANGLE,
              MAIN_GAUGE_SWEEP,
              Math.max(0, (scale.labels_millions.length - 3) / (scale.labels_millions.length - 1)),
            ),
            endAngle,
          )}
          fill={`url(#${id}-band-red)`}
        />
      )}

      {scale.labels_millions.map((label) => {
        const fraction = label / scale.max_millions;
        const angle = gaugeAngle(MAIN_GAUGE_START_ANGLE, MAIN_GAUGE_SWEEP, fraction);
        const labelPos = polarPoint(cx, cy, labelR, angle);
        return (
          <g key={label}>
            <path
              d={tickPath(cx, cy, tickInner, tickOuter, angle)}
              stroke="#f4fafa"
              strokeWidth={4}
              strokeLinecap="round"
            />
            <text
              x={labelPos.x}
              y={labelPos.y}
              textAnchor="middle"
              dominantBaseline="middle"
              className="cockpit-gauge-number"
              fill="#f4fafa"
            >
              {label}
            </text>
          </g>
        );
      })}

      {scale.labels_millions.slice(0, -1).map((label) =>
        [1, 2, 3, 4].map((minor) => {
          const value = label + (minor * scale.step_millions) / 5;
          const fraction = value / scale.max_millions;
          const angle = gaugeAngle(MAIN_GAUGE_START_ANGLE, MAIN_GAUGE_SWEEP, fraction);
          return (
            <path
              key={`${label}-${minor}`}
              d={tickPath(cx, cy, minorInner, tickOuter, angle)}
              stroke="#f4fafa"
              strokeOpacity={0.8}
              strokeWidth={2}
            />
          );
        }),
      )}

      {!planUnusable && (
        <PlanMarker cx={cx} cy={cy} r={tickOuter} angle={gaugeAngle(MAIN_GAUGE_START_ANGLE, MAIN_GAUGE_SWEEP, scale.marker_fraction)} />
      )}

      {planUnusable && (
        <text
          x={cx}
          y={cy - faceR + 42}
          textAnchor="middle"
          className="cockpit-gauge-neutral"
          fill="#8a999e"
          role="img"
          aria-label="План не задан"
        >
          ⚙
        </text>
      )}

      {/* Unit label curves along the dial's own rim, in the free
          (tick-less) wedge between the "0" tick (180deg) and the sweep's
          own end (90deg) - a real curved arc of text now (an invisible
          <path> for it to flow along via <textPath>), not just a straight
          label rotated into that gap, per product feedback 2026-10-06:
          "располагаем по окружность (по дуге) с изгибом". The dial's
          center no longer shows the sum at all (removed the same round,
          see below), so this is clear of anything else regardless of
          needle angle.

          The path is built starting AT the "0" tick (180deg) and curving
          toward the sweep's end (90deg), not the other way round, for two
          reasons raised together, 2026-10-06: (1) "она должна начинаться
          от нуля" - the text should read starting from the "0" tick, and
          (2) going 90->180 instead (the first version here) put the
          glyphs' "up" on the path's INNER side, which textPath renders
          upside-down/mirrored for an arc curving this way - a well-known
          SVG textPath gotcha, confirmed by that same screenshot. Sweep
          flag is 0 (not arcPath's hardcoded 1) because this now traces
          BACKWARD through the angle range (180 down to 90) to get there -
          same quarter-circle shape, opposite direction.

          Follow-up, same day (two rounds): first "она должна начинаться
          от нуля" (start right at the tick), "спусти ниже" (lower),
          "расстояние между символами больше" (more letter-spacing - see
          .cockpit-unit-label), "дугу побольше" (more curved) - tried a
          tighter, non-concentric arc for that round. Then corrected again:
          "еще ниже, чтобы шло по одной линии с нижней частью риски, прям
          по кругу циферблата" - actually concentric with the dial after
          all, riding the tick marks' own radius (tickOuter) rather than a
          custom one, plus "отступи от риски... примерно на 2 цифры" - a
          real gap before the text starts, not flush against the tick
          (startOffset below, in px - a fixed length survives a radius
          change better than a path-relative percentage would). */}
      {(() => {
        const arcStart = polarPoint(cx, cy, tickOuter, 180);
        const arcEnd = polarPoint(cx, cy, tickOuter, 90);
        const unitArcD = `M ${arcStart.x} ${arcStart.y} A ${tickOuter} ${tickOuter} 0 0 0 ${arcEnd.x} ${arcEnd.y}`;
        return (
          <>
            <path id={`${id}-unit-arc`} d={unitArcD} fill="none" stroke="none" />
            <text className="cockpit-unit-label" fill="#8a999e">
              <textPath href={`#${id}-unit-arc`} startOffset="32">
                х1000000руб.
              </textPath>
            </text>
          </>
        );
      })()}

      {gauge.overflow && (
        <text
          x={cx}
          y={cy + 97}
          textAnchor="middle"
          className="cockpit-money-flag"
          fill="#3ebecc"
          role="img"
          aria-label="Перевыполнение плана"
          style={moneyOffsetStyle}
        >
          ↑
        </text>
      )}
      {gauge.underflow && (
        <text
          x={cx}
          y={cy + 97}
          textAnchor="middle"
          className="cockpit-money-flag"
          fill="#ff6b5e"
          role="img"
          aria-label="Отрицательная сумма"
          style={moneyOffsetStyle}
        >
          ↓
        </text>
      )}
      {hasUnattributedRevenue && (
        <text
          x={cx - faceR + 34}
          y={cy - faceR + 42}
          textAnchor="middle"
          className="cockpit-gauge-neutral"
          fill="#e7c663"
          role="img"
          aria-label="Часть выручки не привязана к цеху"
        >
          ⚠
        </text>
      )}

      <Needle
        cx={cx}
        cy={cy}
        length={faceR - 24}
        angle={displayAngle}
        hubR={26}
        scale={1.3}
        transitionMs={blipDone ? undefined : revealDurationMs}
      />
    </g>
  );
}

// See MainGauge's own MONEY_SHIFT_PX comment - same issue, same fix: 0 is
// at the bottom here too (PAYMENTS_GAUGE_START_ANGLE), so a small payments
// figure points the needle straight down through this centered readout.
// Scaled to this dial's smaller size (90 * (PAY needle length / MAIN
// needle length)).
const PAYMENTS_MONEY_SHIFT_PX = 55;
const PAYMENTS_MONEY_OFFSET_STYLE = { transform: `translateX(${PAYMENTS_MONEY_SHIFT_PX}px)` };

function PaymentsGauge({ payments, gauge }: { payments: number; gauge: GaugeReading }) {
  const id = useId();
  const { cx, cy, r } = PAY;
  const faceR = r - 22;
  const bandR = r - 40;
  const tickOuter = r - 26;
  const tickInner = r - 36;
  const minorInner = r - 30;
  const labelR = tickInner - 24;

  const endAngle = PAYMENTS_GAUGE_START_ANGLE + PAYMENTS_GAUGE_SWEEP;
  const needleAngle = gaugeAngle(PAYMENTS_GAUGE_START_ANGLE, PAYMENTS_GAUGE_SWEEP, gauge.needle_fraction);

  // Same shared scale as the main gauge (see cockpit_service.get_snapshot -
  // both readings are always computed against one scale) - numbered major
  // ticks + minor ticks here too, not just an unlabeled ring, so this dial
  // reads the same way the main one does.
  const scale = gauge.scale;

  return (
    <g aria-hidden="true">
      <ChromeRing cx={cx} cy={cy} r={r} width={10} id={`${id}-chrome`} />
      <DialFace id={`${id}-face`} cx={cx} cy={cy} r={faceR} vertical />

      <GlowBand
        d={arcPath(cx, cy, bandR, PAYMENTS_GAUGE_START_ANGLE, endAngle)}
        color="#596063"
        width={8}
        coreOpacity={0.8}
        haloOpacity={0.35}
      />
      <GlowBand
        d={arcPath(cx, cy, bandR, gaugeAngle(PAYMENTS_GAUGE_START_ANGLE, PAYMENTS_GAUGE_SWEEP, 0.88), endAngle)}
        color="#f3202d"
        width={10}
      />

      {scale.labels_millions.map((label) => {
        const fraction = label / scale.max_millions;
        const angle = gaugeAngle(PAYMENTS_GAUGE_START_ANGLE, PAYMENTS_GAUGE_SWEEP, fraction);
        const labelPos = polarPoint(cx, cy, labelR, angle);
        return (
          <g key={label}>
            <path
              d={tickPath(cx, cy, tickInner, tickOuter, angle)}
              stroke="#f4fafa"
              strokeWidth={2.4}
              strokeLinecap="round"
            />
            <text
              x={labelPos.x}
              y={labelPos.y}
              textAnchor="middle"
              dominantBaseline="middle"
              className="cockpit-gauge-number-sm"
              fill="#f4fafa"
            >
              {label}
            </text>
          </g>
        );
      })}

      {scale.labels_millions.slice(0, -1).map((label) =>
        [1, 2, 3, 4].map((minor) => {
          const value = label + (minor * scale.step_millions) / 5;
          const fraction = value / scale.max_millions;
          const angle = gaugeAngle(PAYMENTS_GAUGE_START_ANGLE, PAYMENTS_GAUGE_SWEEP, fraction);
          return (
            <path
              key={`${label}-${minor}`}
              d={tickPath(cx, cy, minorInner, tickOuter, angle)}
              stroke="#8a999e"
              strokeWidth={1.1}
            />
          );
        }),
      )}

      {/* Shifted clear of the needle's own downward sweep, same reasoning
          as MainGauge's MONEY_SHIFT_PX above (0 is now at 270°/left, so the
          needle points straight down at fraction=1 here too) - scaled down
          from the main gauge's 90px by this dial's own shorter needle
          (faceR-16 here vs faceR-24 there). */}
      <text
        x={cx}
        y={cy + 62}
        textAnchor="middle"
        className="cockpit-money-secondary"
        fill="#eafcff"
        style={PAYMENTS_MONEY_OFFSET_STYLE}
      >
        {formatRub(payments)} ₽
      </text>
      {gauge.overflow && (
        <text
          x={cx}
          y={cy + 84}
          textAnchor="middle"
          className="cockpit-money-flag-sm"
          fill="#3ebecc"
          aria-hidden="true"
          style={PAYMENTS_MONEY_OFFSET_STYLE}
        >
          ↑
        </text>
      )}

      {/* Rendered unconditionally - even with no plan/scale, the backend
          still returns a neutral needle_fraction=0, which this points at
          the gauge's own resting angle, per product spec ("шкалу и
          стрелку сделай нейтральными", not absent). */}
      <Needle cx={cx} cy={cy} length={faceR - 16} angle={needleAngle} hubR={13} scale={0.7} />
    </g>
  );
}

// Exact same glyphs as components/planner/MissedCallsBadge.tsx /
// LeadsBadge.tsx (per product feedback, 2026-09-29: "как сделаны на
// планере") - filled shapes, not outline strokes like the other lamps here.
const PHONE_PATH =
  "M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1C10.9 21 3 13.1 3 3.6 3 3 3.4 2.6 4 2.6h3.4c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8Z";
const ENVELOPE_PATH =
  "M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm1 2.4V17h14V7.4l-6.4 4.8a1 1 0 0 1-1.2 0L5 7.4Zm.9-.4L12 11l6.1-4H5.9Z";
const REFRESH_PATH =
  "M4 12a8 8 0 0 1 14-5.3L21 4v6h-6l2.6-2.6A6 6 0 0 0 6 12Z M20 12a8 8 0 0 1-14 5.3L3 20v-6h6l-2.6 2.6A6 6 0 0 0 18 12Z";

/** Top-right "lamp" row - all gray by default (per product feedback,
 * 2026-09-29: the old per-icon warn/ok tint coloring is gone), except the
 * phone/envelope lamps, which mirror the Planner's own missed-calls/leads
 * badges and light up red exactly when those badges would show a count.
 * The "sync" lamp doubles as the page's only refresh control now that the
 * topbar (and its own dedicated refresh button) is gone. */
// Visible window: this many rows show at once, the middle one being the
// "selected" slot - see DepartmentWheel below. Row height is a fixed CSS
// px value (WHEEL_ROW_H) so scroll-position <-> index math stays exact
// (rows are forced to a single line via CSS - see .cockpit-dept-wheel-row).
// Sized up per product feedback, 2026-09-30 ("делай еще крупнее").
const WHEEL_VISIBLE_ROWS = 3;
const WHEEL_ROW_H = 48;
// How far the pointer has to move before a press counts as "dragging the
// drum" rather than "clicking a row" - below this, pointer capture is
// never taken, so the row button's own native click still fires normally
// (per product feedback, 2026-09-30: "надо чтобы кроме колесика можно
// было ткнуть мышкой в значение" - an earlier version captured the
// pointer unconditionally on press, which ate every click).
const DRAG_THRESHOLD_PX = 6;

const MONTH_ABBR = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];

/** Click-to-open month+year picker for the period label (per product
 * feedback, 2026-09-30: "при клике... должен открываться календарь но не
 * по датам а по месяцам и годам"). A plain positioned panel, not
 * AdminModal - that one's styled for the Settings pages, not this dark
 * instrument-panel chrome. Closes on an outside click or Escape; a future
 * month is shown but disabled - no data can exist there yet, and the
 * current month is always where this reopens (see CockpitView's `period`
 * state: null until the operator actively picks something else). */
function PeriodPicker({
  year,
  month,
  onSelect,
  onClose,
}: {
  year: number;
  month: number; // 1-12, currently selected
  onSelect: (year: number, month: number) => void;
  onClose: () => void;
}) {
  const [viewYear, setViewYear] = useState(year);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handlePointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) onClose();
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  const now = new Date();
  const currentYear = now.getFullYear();
  const currentMonth = now.getMonth() + 1;

  return (
    <div className="cockpit-period-picker" ref={rootRef}>
      <div className="cockpit-period-picker-header">
        <button
          type="button"
          className="cockpit-period-picker-nav"
          onClick={() => setViewYear((y) => y - 1)}
          aria-label="Предыдущий год"
        >
          ‹
        </button>
        <span>{viewYear}</span>
        <button
          type="button"
          className="cockpit-period-picker-nav"
          onClick={() => setViewYear((y) => y + 1)}
          disabled={viewYear >= currentYear}
          aria-label="Следующий год"
        >
          ›
        </button>
      </div>
      <div className="cockpit-period-picker-grid">
        {MONTH_ABBR.map((label, index) => {
          const m = index + 1;
          const disabled = viewYear === currentYear && m > currentMonth;
          const selected = viewYear === year && m === month;
          return (
            <button
              key={label}
              type="button"
              className="cockpit-period-picker-month"
              data-selected={selected || undefined}
              disabled={disabled}
              onClick={() => onSelect(viewYear, m)}
            >
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Цех filter, a real spinning drum (per product feedback, 2026-09-30:
 * "барабан который можно вращать мышкой или скролом" - not a flat list,
 * not dots). Three ways to move it, each tuned for what it's good at:
 * - Mouse wheel: intercepted and stepped exactly one row per notch (native
 *   wheel-driven scrolling is too imprecise to reliably land on one value
 *   - per product feedback, 2026-09-30: "поймать каждое значение почти
 *   нереально").
 * - Touch/trackpad: native scroll + CSS scroll-snap, since a finger
 *   already tracks 1:1 and snapping to the nearest row on release is the
 *   right feel there.
 * - Mouse drag: a small pointer-drag handler so a plain mouse can grab and
 *   spin it too (distinct from a plain click via DRAG_THRESHOLD_PX above).
 * - A row can always just be clicked directly to jump to it.
 * Every row is the same size; only color (gray vs. the bright cyan-white
 * the main gauge's own sum uses) marks which one is centered/selected -
 * per product feedback, explicitly not "small vs big". Scales to a client
 * with ~20 цехов without ever showing more than WHEEL_VISIBLE_ROWS labels
 * at once. */
function DepartmentWheel({
  items,
  selectedIndex,
  onSelect,
}: {
  items: { id: string; label: string }[];
  selectedIndex: number;
  onSelect: (index: number) => void;
}) {
  const n = items.length;
  const trackRef = useRef<HTMLDivElement>(null);
  const dragState = useRef<{ startY: number; startScrollTop: number; dragging: boolean; pointerId: number } | null>(
    null,
  );
  const hasCentered = useRef(false);

  // Renders 3 back-to-back copies of the list (per product feedback,
  // 2026-09-30: "закольцовано, можно крутить бесконечно в обе стороны") -
  // the scroll position is always kept within the MIDDLE copy's own
  // render-index range [n, 2n); scrolling past either edge of it triggers
  // an instant (invisible, since every copy is identical) jump back into
  // the middle copy - see settleScroll below. This is the standard
  // "infinite" scroller trick and needs no real infinite DOM.
  const loopItems = [...items, ...items, ...items];

  // scrollTop=0 puts render-index 0's own TOP edge at the viewport's top,
  // not its center - CENTER_OFFSET (1 row, for a 3-row window) is the
  // correction so the row we mean to select actually lands in the middle
  // slot instead of the top one (per product feedback, 2026-09-30:
  // "выбираться должен тот что по центру, а не сверху" - this was a real
  // off-by-one, not just a CSS/color question).
  const CENTER_OFFSET = Math.floor(WHEEL_VISIBLE_ROWS / 2);

  const scrollToRenderIndex = (renderIndex: number, behavior: ScrollBehavior) => {
    trackRef.current?.scrollTo({ top: (renderIndex - CENTER_OFFSET) * WHEEL_ROW_H, behavior });
  };

  const nearestRenderIndex = () => {
    const el = trackRef.current;
    if (!el) return n + selectedIndex;
    return Math.round(el.scrollTop / WHEEL_ROW_H) + CENTER_OFFSET;
  };

  const toLogical = (renderIndex: number) => ((renderIndex % n) + n) % n;

  // Called once a scroll gesture (of any kind) has settled: reports the
  // logical selection, and - only now, never mid-gesture - silently snaps
  // back into the middle copy if the drum drifted into an outer one.
  const settleScroll = () => {
    const renderIndex = nearestRenderIndex();
    const logical = toLogical(renderIndex);
    if (logical !== selectedIndex) onSelect(logical);
    if (renderIndex < n || renderIndex >= 2 * n) {
      scrollToRenderIndex(n + logical, "auto");
    }
  };

  // Centers in the middle copy exactly once on mount (unconditionally -
  // scrollTop starts at 0, which is the very edge of the loop, not a
  // position that already "agrees" with any selection), then only nudges
  // the drum for genuine external selectedIndex changes afterward -
  // skipped when the scroll position already agrees, so this never fights
  // the user's own in-progress scroll/drag/wheel (which is what reports
  // those changes in the first place).
  useEffect(() => {
    if (!hasCentered.current) {
      hasCentered.current = true;
      scrollToRenderIndex(n + selectedIndex, "auto");
      return;
    }
    if (toLogical(nearestRenderIndex()) !== selectedIndex) {
      scrollToRenderIndex(n + selectedIndex, "auto");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIndex, n]);

  // Mouse wheel: exactly one row per notch, not native free-scrolling -
  // see module comment. React's onWheel is passive by default (can't
  // preventDefault there), so this is a real, non-passive DOM listener.
  useEffect(() => {
    const el = trackRef.current;
    if (!el) return;
    const onWheelNative = (e: WheelEvent) => {
      e.preventDefault();
      const dir = e.deltaY > 0 ? 1 : -1;
      const next = nearestRenderIndex() + dir;
      scrollToRenderIndex(next, "smooth");
      const logical = toLogical(next);
      if (logical !== selectedIndex) onSelect(logical);
    };
    el.addEventListener("wheel", onWheelNative, { passive: false });
    return () => el.removeEventListener("wheel", onWheelNative);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [n, selectedIndex, onSelect]);

  const scrollEndTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleScroll = () => {
    if (scrollEndTimer.current) clearTimeout(scrollEndTimer.current);
    scrollEndTimer.current = setTimeout(settleScroll, 120);
  };

  const handlePointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    const el = trackRef.current;
    if (!el) return;
    // Not captured yet - see handlePointerMove, DRAG_THRESHOLD_PX.
    dragState.current = { startY: e.clientY, startScrollTop: el.scrollTop, dragging: false, pointerId: e.pointerId };
  };

  const handlePointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const el = trackRef.current;
    const state = dragState.current;
    if (!el || !state) return;
    const delta = e.clientY - state.startY;
    if (!state.dragging) {
      if (Math.abs(delta) < DRAG_THRESHOLD_PX) return; // still just a click-in-progress
      state.dragging = true;
      el.setPointerCapture(state.pointerId);
      el.classList.add("cockpit-dept-wheel--dragging");
    }
    el.scrollTop = state.startScrollTop - delta;
  };

  const endDrag = (e: ReactPointerEvent<HTMLDivElement>) => {
    const el = trackRef.current;
    const state = dragState.current;
    if (!el || !state) return;
    dragState.current = null;
    if (!state.dragging) return; // a plain click - let the row's own onClick handle it
    el.releasePointerCapture(e.pointerId);
    el.classList.remove("cockpit-dept-wheel--dragging");
    const renderIndex = nearestRenderIndex();
    scrollToRenderIndex(renderIndex, "smooth");
    const logical = toLogical(renderIndex);
    if (logical !== selectedIndex) onSelect(logical);
  };

  return (
    <div className="cockpit-dept-wheel-wrap">
      <div
        ref={trackRef}
        className="cockpit-dept-wheel"
        style={{ height: WHEEL_ROW_H * WHEEL_VISIBLE_ROWS }}
        onScroll={handleScroll}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        role="listbox"
        aria-label="Подразделение"
      >
        {loopItems.map((item, renderIndex) => (
          <button
            key={`${item.id || "all"}-${renderIndex}`}
            type="button"
            role="option"
            aria-selected={toLogical(renderIndex) === selectedIndex}
            className="cockpit-dept-wheel-row"
            style={{ height: WHEEL_ROW_H }}
            data-selected={toLogical(renderIndex) === selectedIndex}
            onClick={() => {
              scrollToRenderIndex(renderIndex, "smooth");
              const logical = toLogical(renderIndex);
              if (logical !== selectedIndex) onSelect(logical);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function WarningIcons({
  missedCallsCount,
  openLeadsCount,
  onRefresh,
  refreshing,
}: {
  missedCallsCount: number;
  openLeadsCount: number;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const icons: {
    key: string;
    label: string;
    path: string;
    filled?: boolean;
    active?: boolean;
    onClick?: () => void;
    spinning?: boolean;
  }[] = [
    { key: "warn", label: "Предупреждения — демо, действие пока не назначено", path: "M12 2 L23 21 H1 Z M12 9v6 M12 17.5v.1" },
    { key: "phone", label: "Пропущенные звонки", path: PHONE_PATH, filled: true, active: missedCallsCount > 0 },
    { key: "leads", label: "Новые заявки", path: ENVELOPE_PATH, filled: true, active: openLeadsCount > 0 },
    { key: "pay", label: "Платежи — демо, действие пока не назначено", path: "M2 6h20v13H2Z M2 10h20 M6 16h4" },
    { key: "sync", label: "Обновить данные", path: REFRESH_PATH, onClick: onRefresh, spinning: refreshing },
    { key: "service", label: "Сервис — демо, действие пока не назначено", path: "M14.7 6.3a4 4 0 0 1-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 1 5.4-5.4L21 6l-3-3Z" },
  ];
  return (
    <div className="cockpit-warning-grid" role="group" aria-label="Индикаторы">
      {icons.map((icon) => (
        <button
          key={icon.key}
          type="button"
          className="cockpit-warning-icon"
          data-active={icon.active ?? false}
          aria-label={icon.label}
          onClick={icon.onClick}
        >
          <svg
            viewBox="0 0 24 24"
            width={30}
            height={30}
            aria-hidden="true"
            className={icon.spinning ? "cockpit-warning-icon-spin" : undefined}
          >
            {icon.filled ? (
              <path d={icon.path} fill="currentColor" />
            ) : (
              <path d={icon.path} fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
            )}
          </svg>
        </button>
      ))}
    </div>
  );
}

// Originally a minimal notch, no letters, per the product spec ("Вместо
// E/F, C/H используй минимальные отметки краёв шкалы"). Product feedback,
// 2026-10-05, reversed that for the revenue strip specifically ("подпиши
// как пишут на индикаторе топлива... Empty и Full") - `label` is optional
// so DebtCapsule's ДЗ/КЗ marks (no real 0..100% scale to label the ends
// of) keep the original plain dot.
function StripEdgeMark({ align, label }: { align: "start" | "end"; label?: string }) {
  if (label) {
    return <span className={`cockpit-strip-edge-label cockpit-strip-edge-label--${align}`}>{label}</span>;
  }
  return <span className={`cockpit-strip-edge cockpit-strip-edge--${align}`} />;
}

/** Month-to-date revenue vs. this scope's own Бюджет-page plan (per product
 * ask, 2026-10-03: replaces the old fixed "2 400 000 ₽" demo fixture with
 * real data, then switched from the dial's own gauge-scale ceiling to the
 * Бюджет page's "Выручка план" cell for this month/scope - see
 * cockpit_service._budget_plan_revenue) - 0 at the left edge, that plan at
 * the right, filled to however much of it is already real (closed)
 * revenue. Neither end is labeled with a number (per that same ask) - the
 * actual fact value is printed small below instead. No plan entered yet on
 * the Бюджет page has nothing to divide by, so the strip just reads empty
 * rather than guessing a scale. */
function RevenueProgressStrip({
  revenue,
  planRub,
  nzpActive,
  effectiveRevenue,
}: {
  revenue: number;
  planRub: number;
  /** Same НЗП toggle the main gauge's own needle already reacts to (see
   * MainGauge's displayValue) - this strip (and the digital row above it,
   * see InstrumentCluster) now follows it too, product ask, 2026-10-07:
   * before, pressing НЗП only moved the needle with nothing printed
   * anywhere confirming by how much - the gauge's own central sum that
   * used to show this was removed a day earlier per a separate ask. */
  nzpActive: boolean;
  effectiveRevenue: number;
}) {
  const displayRevenue = nzpActive ? effectiveRevenue : revenue;
  const segments = 9;
  const filledFraction = planRub > 0 ? Math.min(1, Math.max(0, displayRevenue / planRub)) : 0;
  return (
    <div className="cockpit-strip">
      <div className="cockpit-strip-segments">
        {Array.from({ length: segments }, (_, i) => (
          <span key={i} className={i / segments < filledFraction ? "cockpit-seg cockpit-seg--on" : "cockpit-seg"} />
        ))}
      </div>
      <div className="cockpit-strip-footer">
        <StripEdgeMark align="start" label="E" />
        <span className="cockpit-strip-value">{formatRub(displayRevenue)} ₽</span>
        <StripEdgeMark align="end" label="F" />
      </div>
    </div>
  );
}

/** ДЗ/КЗ - per product spec, 2026-10-03: these never represent a real 0..100%
 * scale (there's no natural "max" to compare either figure against), so the
 * fill is always a fixed 70% regardless of the real amount - only the
 * printed figure below is real data. ДЗ (receivables) is real (see
 * cockpit_service._receivables); КЗ (payables) has no data source defined
 * yet and stays a placeholder, flagged with the same DEMO tag the whole
 * block used to carry. */
const DEBT_CAPSULE_FIXED_FILL = 0.7;
const KZ_PLACEHOLDER_RUB = 1_700_000;

function DebtCapsule({
  label,
  value,
  tone,
  demo,
  onClick,
}: {
  label: string;
  value: number;
  tone: "receivable" | "payable";
  demo?: boolean;
  /** Present only for ДЗ (see PaymentsDebtStack) - renders this as a real
   * <button> instead of decorative markup, since КЗ has no real underlying
   * data/drill-down to link to yet. */
  onClick?: () => void;
}) {
  const inner = (
    <>
      {demo && <span className="cockpit-demo-tag cockpit-demo-tag--corner">DEMO</span>}
      <span className="cockpit-debt-capsule-label">{label}</span>
      <div className="cockpit-capsule">
        <div className="cockpit-capsule-fill" style={{ width: `${DEBT_CAPSULE_FIXED_FILL * 100}%` }} />
      </div>
      <div className="cockpit-strip-footer">
        <StripEdgeMark align="start" />
        <span className="cockpit-strip-value">{formatRub(value)} ₽</span>
        <StripEdgeMark align="end" />
      </div>
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        className={`cockpit-debt-capsule cockpit-debt-capsule--${tone} cockpit-debt-capsule--clickable`}
        onClick={onClick}
        aria-label={`Открыть заказ-наряды, формирующие ${label}`}
      >
        {inner}
      </button>
    );
  }

  return (
    <div className={`cockpit-debt-capsule cockpit-debt-capsule--${tone}`} aria-hidden="true">
      {inner}
    </div>
  );
}

/** Выручка strip - stays on the right under the "Drive" lettering (per
 * product feedback, 2026-10-04: moved well down the panel and enlarged
 * ~2x - see .cockpit-revenue-stack - after an earlier round had grouped it
 * together with ДЗ/КЗ into one combined right-side stack; that grouping is
 * gone, this is now independently positioned). */
function RevenueStack({
  revenue,
  planRub,
  nzpActive,
  effectiveRevenue,
}: {
  revenue: number;
  planRub: number;
  nzpActive: boolean;
  effectiveRevenue: number;
}) {
  return (
    <div className="cockpit-revenue-stack" aria-hidden="true">
      <RevenueProgressStrip
        revenue={revenue}
        planRub={planRub}
        nzpActive={nzpActive}
        effectiveRevenue={effectiveRevenue}
      />
    </div>
  );
}

/** ДЗ/КЗ - moved back so their combined middle sits under the payments
 * gauge's own center (per product feedback, 2026-10-04: "перемещаем
 * обратно, примерно их середина под серединой циферблата с оплатами"),
 * ~50% bigger than before - see .cockpit-payments-stack. Previously grouped
 * with the revenue strip into one right-side stack; split back out here.
 * ДЗ is clickable - opens the Work Orders list filtered to exactly the
 * orders behind that figure (see backend
 * work_order_query_service.list_work_orders's only_receivables); КЗ has no
 * real data source yet, so it stays decorative. */
function PaymentsDebtStack({
  receivables,
  workshopId,
}: {
  receivables: number;
  workshopId: string;
}) {
  const router = useRouter();

  const openReceivables = () => {
    const params = new URLSearchParams({ only_receivables: "1" });
    if (workshopId) params.set("workshop_id", workshopId);
    router.push(`/work-orders?${params.toString()}`);
  };

  return (
    <div className="cockpit-payments-stack">
      <div className="cockpit-payments-stack-row cockpit-payments-stack-row--dz">
        <DebtCapsule label="ДЗ" value={receivables} tone="receivable" onClick={openReceivables} />
      </div>
      <div className="cockpit-payments-stack-row cockpit-payments-stack-row--kz">
        <DebtCapsule label="КЗ" value={KZ_PLACEHOLDER_RUB} tone="payable" demo />
      </div>
    </div>
  );
}

/** The full SVG instrument cluster - see product spec sections 2-9. Takes
 * already-resolved numbers (Decimal strings parsed to number only here, at
 * the very last step, per spec: "числовое преобразование на frontend
 * допустимо только для угла стрелки"). */
export function InstrumentCluster({
  revenue,
  effectiveRevenue,
  payments,
  receivables,
  budgetPlanRevenue,
  revenueGauge,
  paymentsGauge,
  nzpActive,
  onNzpToggle,
  planUnusable,
  hasUnattributedRevenue,
  workshops,
  workshopId,
  onWorkshopChange,
  periodLabel,
  periodYearMonth,
  onPeriodChange,
  isCustomPeriod,
  onResetPeriod,
  missedCallsCount,
  openLeadsCount,
  onRefresh,
  refreshing,
}: {
  revenue: number;
  effectiveRevenue: number;
  payments: number;
  receivables: number;
  budgetPlanRevenue: number;
  revenueGauge: GaugeReading;
  paymentsGauge: GaugeReading;
  nzpActive: boolean;
  onNzpToggle: () => void;
  planUnusable: boolean;
  hasUnattributedRevenue: boolean;
  workshops: WorkshopOption[];
  workshopId: string;
  onWorkshopChange: (value: string) => void;
  periodLabel: string;
  periodYearMonth: { year: number; month: number };
  onPeriodChange: (year: number, month: number) => void;
  /** True once the operator has picked a month other than the current one
   * (see CockpitView's `period` state) - lights up the reset lamp next to
   * the period label (per product ask, 2026-10-01). */
  isCustomPeriod: boolean;
  onResetPeriod: () => void;
  missedCallsCount: number;
  openLeadsCount: number;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const [periodPickerOpen, setPeriodPickerOpen] = useState(false);

  return (
    <>
      <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="cockpit-svg" role="img" aria-label="Приборная панель">
        <title>{`Выручка ${formatRub(nzpActive ? effectiveRevenue : revenue)} ₽${planUnusable ? ", план не задан" : ""}; оплаты ${formatRub(payments)} ₽`}</title>
        <defs>
          <filter id="cockpit-glow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          {/* Pure blur, no merge - see GlowBand above. Used only on a
              band's own wide halo stroke, which is layered under a second,
              separately-drawn crisp core stroke (that one gets no filter at
              all), rather than merged with it in one filter pass. */}
          <filter id="cockpit-band-blur" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="5" />
          </filter>
        </defs>

        {/* Corpus - thin structural lines (see spec section 2's layering
            order: body first, then side displays/small gauge, then the
            main gauge overlapping its edge). */}
        <path d="M 40 40 Q 824 6 1608 40" fill="none" stroke="#24292b" strokeWidth={2} />
        <path d="M 40 610 Q 824 644 1608 610" fill="none" stroke="#24292b" strokeWidth={2} />
        <path
          d="M 40 240 L 20 260 L 20 420 L 40 440 M 300 230 L 320 250"
          fill="none"
          stroke="#367888"
          strokeOpacity={0.6}
          strokeWidth={1.4}
        />
        <path
          d="M 1608 240 L 1628 260 L 1628 420 L 1608 440 M 1170 130 L 1150 150"
          fill="none"
          stroke="#367888"
          strokeOpacity={0.6}
          strokeWidth={1.4}
        />

        <g filter="url(#cockpit-glow)">
          <PaymentsGauge payments={payments} gauge={paymentsGauge} />
        </g>
        <g filter="url(#cockpit-glow)">
          <MainGauge
            revenue={revenue}
            effectiveRevenue={effectiveRevenue}
            gauge={revenueGauge}
            nzpActive={nzpActive}
            planUnusable={planUnusable}
            hasUnattributedRevenue={hasUnattributedRevenue}
          />
        </g>

        {/* Right side: big decorative "Drive" wordmark + digital rows (see
            spec section 9 for the digital rows; the big letter was plain
            "P" before - per product feedback, 2026-09-30, it's now a big
            "D" followed immediately by small "rive", spelling "Drive",
            with "your business" below it shifted right). */}
        {/* Whole wordmark nudged right+down and sized up ~10% (per product
            feedback, 2026-10-04: "увеличить немного и сдвинуть чуть вправо
            и вниз, чтобы оно было как бы поцентру пустого места" - was
            x=1235/y=340, centered more toward the top of its own free
            space than the middle of it). */}
        <text x={1255} y={360} aria-hidden="true">
          <tspan className="cockpit-letter-d" fill="#f4fafa">
            D
          </tspan>
          {/* Explicit x, not left to flow right after "D" - that flow
              position depends on the actual rendered width of the "D"
              glyph, which varies with whichever font in the stack the
              browser actually has available (e.g. no "Arial Narrow" falls
              back to the much wider "Segoe UI"), producing an
              unpredictable gap - per product feedback, 2026-09-30. */}
          {/* Also an explicit y, not inherited from the parent's 340 -
              sharing D's own baseline made "rive" read as hanging off D's
              foot rather than continuing from it (per product feedback,
              2026-09-30: "буквы не болтались отдельно друг от друга") -
              raised to sit against D's upper-middle instead, the usual fix
              for pairing a huge letter with a small suffix. */}
          <tspan className="cockpit-letter-d-suffix" x={1330} y={343} fill="#8a999e">
            rive
          </tspan>
        </text>
        <text x={1337} y={368} className="cockpit-letter-d-tagline" fill="#8a999e" aria-hidden="true">
          your business
        </text>
        <g className="cockpit-digital-rows" aria-hidden="true">
          {/* Was decorative trip-computer filler ("TOTAL 14852.2 km" / "A
              862.2" / "B 1438.9" / "8.2 л/100км") per spec section 9, until
              product feedback, 2026-10-03: real data now, month-to-date
              revenue over this scope's Бюджет-page plan, both in millions
              of ₽ - moved up under the "D"/tagline instead of down at the
              row this whole group used to fill (a tried "CASH <payments>"
              row above it didn't read well and was dropped). */}
          {/* Centered over the revenue strip below (.cockpit-revenue-stack:
              left=71%, width=23% -> center at 82.5% of VIEW_W=1648 ->
              x=1360), textAnchor="middle" so it stays centered regardless
              of the actual digit count - per product feedback, 2026-10-04:
              "циферки опустить немного и по середине полоски поставить".
              Was x=1235/start-anchored (matched the big "D" letter's own
              x, before the strip itself moved right of where it used to
              sit) at y=408, then 425 - pulled down again, closer to the
              strip's own top edge (.cockpit-revenue-stack's top=74% of
              VIEW_H=650 -> y=481), so it visibly reads as that strip's own
              caption rather than a separate floating line (per product
              feedback, 2026-10-04: "еще чуть пониже, чтобы было понятно,
              что это подпись к этой линии"). */}
          <text x={1360} y={460} textAnchor="middle" className="cockpit-row-line">
            {formatMillions(nzpActive ? effectiveRevenue : revenue)} / {formatMillions(budgetPlanRevenue)} млн
          </text>
        </g>
      </svg>

      {/* Цех filter - replaces the old topbar's <select> (per product
          feedback, 2026-09-29/30: "сделать как раз выбор подразделений
          который сейчас вверху", then "барабан который можно вращать
          мышкой или скролом"). */}
      <div className="cockpit-left-panel">
        <DepartmentWheel
          items={[{ id: "", label: "Вся компания" }, ...workshops.map((w) => ({ id: w.id, label: `${w.department_name} — ${w.workshop_type}` }))]}
          selectedIndex={workshopId === "" ? 0 : Math.max(0, workshops.findIndex((w) => w.id === workshopId) + 1)}
          onSelect={(index) => onWorkshopChange(index === 0 ? "" : workshops[index - 1].id)}
        />
        <div className="cockpit-period-row">
          <div className="cockpit-left-big-wrap">
            <button
              type="button"
              className="cockpit-left-big"
              onClick={() => setPeriodPickerOpen((v) => !v)}
              aria-label={`Выбрать месяц и год, сейчас: ${periodLabel}`}
            >
              {periodLabel}
            </button>
            {periodPickerOpen && (
              <PeriodPicker
                year={periodYearMonth.year}
                month={periodYearMonth.month}
                onSelect={(y, m) => {
                  onPeriodChange(y, m);
                  setPeriodPickerOpen(false);
                }}
                onClose={() => setPeriodPickerOpen(false)}
              />
            )}
          </div>
          <button
            type="button"
            className="cockpit-period-reset"
            data-active={isCustomPeriod}
            disabled={!isCustomPeriod}
            onClick={onResetPeriod}
            aria-label={isCustomPeriod ? "Сбросить на текущий месяц" : "Показан текущий месяц"}
            title={isCustomPeriod ? "Сбросить на текущий месяц" : "Показан текущий месяц"}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- fixed
                small decorative icon, next/image's optimization pipeline
                buys nothing here. */}
            <img src="/icon-new.png" alt="" className="cockpit-period-reset-icon" />
          </button>
        </div>
      </div>

      {/* НЗП - moved off the old topbar onto the cluster itself, above the
          two gauges roughly where their rims cross (per product feedback,
          2026-09-29: "над циферблатами, примерно над тем местом где они
          пересекаются") - same button, just relocated. */}
      <div className="cockpit-nzp-overlay">
        <NzpToggle active={nzpActive} onToggle={onNzpToggle} />
      </div>

      <WarningIcons
        missedCallsCount={missedCallsCount}
        openLeadsCount={openLeadsCount}
        onRefresh={onRefresh}
        refreshing={refreshing}
      />

      <div className="cockpit-strips">
        <RevenueStack
          revenue={revenue}
          planRub={budgetPlanRevenue}
          nzpActive={nzpActive}
          effectiveRevenue={effectiveRevenue}
        />
        <PaymentsDebtStack receivables={receivables} workshopId={workshopId} />
      </div>
    </>
  );
}
