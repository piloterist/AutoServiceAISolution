"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export type StatusSlice = {
  label: string;
  value: number;
};

// Same fixed categorical order as DepartmentDonutChart (Okabe-Ito,
// colorblind-safe) - a different chart/dimension, so reusing the same hue
// sequence is fine (color identifies "1st/2nd/3rd slice of this chart", not
// a specific department vs status crossing over).
const CATEGORICAL_COLORS = [
  "#0072B2", // blue
  "#E69F00", // orange
  "#009E73", // green
  "#CC79A7", // pink
  "#D55E00", // vermillion
  "#56B4E9", // sky blue
  "#F0E442", // yellow
  "#8c8c8c", // grey - overflow slot beyond the 7 named hues
];

const SIZE = 220;
const RADIUS = SIZE / 2;
const INNER_RADIUS = RADIUS * 0.6;
const GAP_DEG = 1.5;

function polarToCartesian(angleDeg: number, radius: number) {
  const angleRad = ((angleDeg - 90) * Math.PI) / 180;
  return {
    x: RADIUS + radius * Math.cos(angleRad),
    y: RADIUS + radius * Math.sin(angleRad),
  };
}

function arcPath(startAngle: number, endAngle: number): string {
  const outerStart = polarToCartesian(startAngle, RADIUS);
  const outerEnd = polarToCartesian(endAngle, RADIUS);
  const innerStart = polarToCartesian(endAngle, INNER_RADIUS);
  const innerEnd = polarToCartesian(startAngle, INNER_RADIUS);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;

  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${RADIUS} ${RADIUS} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerStart.x} ${innerStart.y}`,
    `A ${INNER_RADIUS} ${INNER_RADIUS} 0 ${largeArc} 0 ${innerEnd.x} ${innerEnd.y}`,
    "Z",
  ].join(" ");
}

function pluralWorkOrders(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return "заказ-наряд";
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return "заказ-наряда";
  return "заказ-нарядов";
}

function formatCount(value: number): string {
  return `${value.toLocaleString("ru-RU")} ${pluralWorkOrders(value)}`;
}

export function StatusDonutChart({
  data,
  dateFrom,
  dateTo,
}: {
  data: StatusSlice[];
  /** Plain strings (not a function) - a Server Component parent can't pass
   * functions across the RSC boundary, only serializable data. Used to
   * carry the dashboard's current period into the work-orders link when a
   * slice is clicked. */
  dateFrom?: string;
  dateTo?: string;
}) {
  const router = useRouter();
  const [hovered, setHovered] = useState<number | null>(null);

  const total = data.reduce((sum, d) => sum + d.value, 0);

  if (data.length === 0 || total <= 0) {
    return <p className="chart-empty">Нет данных за выбранный период.</p>;
  }

  const goToStatus = (status: string) => {
    const params = new URLSearchParams();
    params.set("status", status);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    router.push(`/work-orders?${params.toString()}`);
  };

  let cursor = 0;
  const slices = data.map((d, index) => {
    const fraction = d.value / total;
    const sweep = fraction * 360;
    const startAngle = cursor + (sweep > GAP_DEG ? GAP_DEG / 2 : 0);
    const endAngle = cursor + sweep - (sweep > GAP_DEG ? GAP_DEG / 2 : 0);
    cursor += sweep;
    const midAngle = (startAngle + endAngle) / 2;
    const color = CATEGORICAL_COLORS[index % CATEGORICAL_COLORS.length];
    return { ...d, fraction, startAngle, endAngle, midAngle, color };
  });

  const hoveredSlice = hovered !== null ? slices[hovered] : null;
  const labelPoint = hoveredSlice
    ? polarToCartesian(hoveredSlice.midAngle, (RADIUS + INNER_RADIUS) / 2)
    : null;

  return (
    <div className="donut-root">
      <div className="donut-visual" style={{ width: SIZE, height: SIZE }}>
        <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
          {slices.map((slice, index) => (
            <path
              key={slice.label}
              d={arcPath(slice.startAngle, slice.endAngle)}
              fill={slice.color}
              className={hovered === index ? "donut-slice donut-slice-hovered" : "donut-slice"}
              onMouseEnter={() => setHovered(index)}
              onMouseLeave={() => setHovered((current) => (current === index ? null : current))}
              onClick={() => goToStatus(slice.label)}
            />
          ))}
        </svg>

        <div className="donut-center-label">
          <span className="donut-center-value">{formatCount(total)}</span>
          <span className="donut-center-caption">всего за период</span>
        </div>

        {hoveredSlice && labelPoint && (
          <div className="chart-tooltip donut-tooltip" style={{ left: labelPoint.x, top: labelPoint.y }}>
            <strong>{hoveredSlice.label}</strong>
            <span>{formatCount(hoveredSlice.value)}</span>
            <span className="chart-tooltip-muted">{(hoveredSlice.fraction * 100).toFixed(1)}%</span>
          </div>
        )}
      </div>

      <ul className="donut-legend">
        {slices.map((slice, index) => (
          <li
            key={slice.label}
            className={
              hovered === index ? "donut-legend-item donut-legend-item-hovered" : "donut-legend-item"
            }
            onMouseEnter={() => setHovered(index)}
            onMouseLeave={() => setHovered((current) => (current === index ? null : current))}
            onClick={() => goToStatus(slice.label)}
          >
            <span className="donut-swatch" style={{ background: slice.color }} />
            <span className="donut-legend-label">{slice.label}</span>
            <span className="donut-legend-value">{formatCount(slice.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
