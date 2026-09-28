"use client";

import { useId } from "react";

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
import type { GaugeReading } from "@/lib/backend-api";

const VIEW_W = 1648;
const VIEW_H = 650;

const MAIN = { cx: 887, cy: 329, r: 296 };
const PAY = { cx: 489, cy: 335, r: 185 };

function formatRub(value: number): string {
  return value.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
}: {
  cx: number;
  cy: number;
  length: number;
  angle: number;
  hubR: number;
  scale?: number;
}) {
  const w = 10 * scale;
  const tailW = 7 * scale;
  const tail = 28 * scale;
  return (
    <g transform={`rotate(${angle} ${cx} ${cy})`} className="cockpit-needle">
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

      {/* Unit label sits on the rim, in the free (tick-less) wedge between
          the "0" tick and the sweep's own end - following the dial's own
          circumference, like the reference photo's "X1000R/M" - instead of
          the dial's center, which now shows the actual sum instead. */}
      {(() => {
        // Angular middle of the free (tick-less) wedge (90deg..180deg) -
        // equidistant from the "0" tick at 180deg and the max-value tick at
        // 90deg, so this doesn't crowd either.
        const unitPos = polarPoint(cx, cy, labelR, 135);
        return (
          <text x={unitPos.x} y={unitPos.y} textAnchor="middle" className="cockpit-unit-label" fill="#8a999e">
            х1000000руб.
          </text>
        );
      })()}

      {/* The full sum, centered below the needle hub and tail - clear of
          the tail's own swept footprint (hub r=26, tail reaches ~37 from
          center at its longest) so the needle never sits on top of it, per
          product feedback that it was getting partly covered. The needle
          is still the primary reading; this is a legible central digital
          readout, not a dominant overlay. */}
      <text x={cx} y={cy + 75} textAnchor="middle" dominantBaseline="middle" className="cockpit-money-main" fill="#eafcff">
        {formatRub(displayValue)} ₽
      </text>
      {gauge.overflow && (
        <text
          x={cx}
          y={cy + 97}
          textAnchor="middle"
          className="cockpit-money-flag"
          fill="#3ebecc"
          role="img"
          aria-label="Перевыполнение плана"
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

      <Needle cx={cx} cy={cy} length={faceR - 24} angle={needleAngle} hubR={26} scale={1.3} />
    </g>
  );
}

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

      <text x={cx} y={cy + 62} textAnchor="middle" className="cockpit-money-secondary" fill="#eafcff">
        {formatRub(payments)} ₽
      </text>
      {gauge.overflow && (
        <text x={cx} y={cy + 84} textAnchor="middle" className="cockpit-money-flag-sm" fill="#3ebecc" aria-hidden="true">
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

function WarningIcons() {
  // Compact outline icons - real <button>s so they're keyboard focusable
  // and clickable, per spec ("настоящие button... aria-label, действие
  // пока не назначено"), positioned via a small local grid rather than
  // absolute SVG coordinates so focus rings render natively.
  const icons: { key: string; label: string; tone: "down" | "warn" | "ok"; path: string }[] = [
    { key: "warn", label: "Предупреждения", tone: "down", path: "M12 2 L23 21 H1 Z M12 9v6 M12 17.5v.1" },
    { key: "doc", label: "Документы", tone: "down", path: "M5 2h10l4 4v16H5Z M15 2v4h4 M8 12h8 M8 16h8 M8 8h4" },
    { key: "clock", label: "Регламент", tone: "down", path: "M12 12 L12 6 M12 12 L16 14 M12 2a10 10 0 1 0 .1 0Z" },
    { key: "pay", label: "Платежи", tone: "warn", path: "M2 6h20v13H2Z M2 10h20 M6 16h4" },
    { key: "sync", label: "Синхронизация", tone: "ok", path: "M4 12a8 8 0 0 1 14-5.3L21 4v6h-6l2.6-2.6A6 6 0 0 0 6 12Z M20 12a8 8 0 0 1-14 5.3L3 20v-6h6l-2.6 2.6A6 6 0 0 0 18 12Z" },
    { key: "service", label: "Сервис", tone: "down", path: "M14.7 6.3a4 4 0 0 1-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 1 5.4-5.4L21 6l-3-3Z" },
  ];
  return (
    <div className="cockpit-warning-grid" role="group" aria-label="Предупреждения — демо, действие пока не назначено">
      {icons.map((icon) => (
        <button
          key={icon.key}
          type="button"
          className={`cockpit-warning-icon cockpit-warning-icon--${icon.tone}`}
          aria-label={`${icon.label} — демо, действие пока не назначено`}
        >
          <svg viewBox="0 0 24 24" width={20} height={20} aria-hidden="true">
            <path d={icon.path} fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      ))}
    </div>
  );
}

// Neither strip uses automotive edge letters (E/F, C/H) - the product
// spec explicitly asks for minimal edge marks/pictograms instead ("Вместо
// E/F, C/H используй минимальные отметки краёв шкалы и небольшие
// пиктограммы без финансовых названий").
function StripEdgeMark({ align }: { align: "start" | "end" }) {
  return <span className={`cockpit-strip-edge cockpit-strip-edge--${align}`} />;
}

function ReceivablesStrip() {
  const segments = 9;
  const filledFraction = 0.6; // demo fixture - see product spec section 8
  return (
    <div className="cockpit-strip cockpit-strip--receivables" aria-hidden="true">
      <span className="cockpit-demo-tag cockpit-demo-tag--corner">DEMO</span>
      <div className="cockpit-strip-segments">
        {Array.from({ length: segments }, (_, i) => (
          <span key={i} className={i / segments < filledFraction ? "cockpit-seg cockpit-seg--on" : "cockpit-seg"} />
        ))}
      </div>
      <div className="cockpit-strip-footer">
        <StripEdgeMark align="start" />
        <span className="cockpit-strip-value">2 400 000 ₽</span>
        <StripEdgeMark align="end" />
      </div>
    </div>
  );
}

function PayablesCapsule() {
  const filledFraction = 0.425; // demo fixture - see product spec section 8
  return (
    <div className="cockpit-strip cockpit-strip--payables" aria-hidden="true">
      <span className="cockpit-demo-tag cockpit-demo-tag--corner">DEMO</span>
      <div className="cockpit-capsule">
        <div className="cockpit-capsule-fill" style={{ width: `${filledFraction * 100}%` }} />
      </div>
      <div className="cockpit-strip-footer">
        <StripEdgeMark align="start" />
        <span className="cockpit-strip-value">1 700 000 ₽</span>
        <StripEdgeMark align="end" />
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
  revenueGauge,
  paymentsGauge,
  nzpActive,
  planUnusable,
  hasUnattributedRevenue,
}: {
  revenue: number;
  effectiveRevenue: number;
  payments: number;
  revenueGauge: GaugeReading;
  paymentsGauge: GaugeReading;
  nzpActive: boolean;
  planUnusable: boolean;
  hasUnattributedRevenue: boolean;
}) {
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

        {/* Right side: big decorative "P" + digital rows (see spec section 9). */}
        <text x={1325} y={345} textAnchor="middle" className="cockpit-letter-p" fill="#f4fafa" aria-hidden="true">
          P
        </text>
        <g className="cockpit-digital-rows" aria-hidden="true">
          <text x={1200} y={395} className="cockpit-row-line">
            TOTAL 14852.2 km
          </text>
          <text x={1200} y={430} className="cockpit-row-sub">
            A 862.2
          </text>
          <text x={1345} y={430} className="cockpit-row-sub">
            B 1438.9
          </text>
          <text x={1200} y={470} className="cockpit-row-line">
            8.2 л/100км
          </text>
        </g>
      </svg>

      <div className="cockpit-left-panel" aria-hidden="true">
        <span className="cockpit-demo-tag">DEMO</span>
        <div className="cockpit-left-row">ПРИВОД AWD</div>
        <div className="cockpit-left-row">РЕЖИМ SPORT</div>
        <div className="cockpit-left-row">СТАБИЛИЗАЦИЯ ON</div>
        <div className="cockpit-left-big">18°C</div>
      </div>

      <WarningIcons />

      <div className="cockpit-strips">
        <ReceivablesStrip />
        <PayablesCapsule />
      </div>
    </>
  );
}
