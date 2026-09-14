"use client";

import { useState } from "react";

export type MonthlyPoint = {
  month: string; // "YYYY-MM"
  work_order_count: number;
  total_amount: string;
};

const MONTH_LABELS = [
  "янв",
  "фев",
  "мар",
  "апр",
  "май",
  "июн",
  "июл",
  "авг",
  "сен",
  "окт",
  "ноя",
  "дек",
];

function monthLabel(month: string): string {
  const [year, m] = month.split("-");
  const index = Number(m) - 1;
  return `${MONTH_LABELS[index] ?? m} ${year}`;
}

function formatCompact(value: number): string {
  if (value >= 1_000_000) return (value / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (value >= 1_000) return (value / 1_000).toFixed(0) + "K";
  return String(Math.round(value));
}

function formatAmount(value: number): string {
  return `${value.toLocaleString("ru-RU")} ₽`;
}

const CHART_HEIGHT = 220;

/** Line chart for the revenue trend - a bar chart per-month is a fine
 * comparison view, but "how is revenue changing" (the reason this exists
 * alongside MonthlyBarChart) reads much faster as a line: the eye follows
 * the trend instead of comparing 12 separate bar heights. Single series, so
 * no legend box - the card title already says what's plotted (per the
 * dataviz skill). */
export function MonthlyTrendChart({ data }: { data: MonthlyPoint[] }) {
  const [hovered, setHovered] = useState<number | null>(null);

  if (data.length === 0) {
    return <p className="chart-empty">Нет данных за выбранный период.</p>;
  }

  const values = data.map((point) => Number(point.total_amount));
  const maxValue = Math.max(...values, 1);
  const niceMax = Math.ceil(maxValue / 4) * 4 || 1;
  const ticks = [0, niceMax / 2, niceMax];

  const n = data.length;
  const xPct = (i: number) => (n === 1 ? 50 : (i / (n - 1)) * 100);
  const yPctFromBottom = (value: number) => (value / niceMax) * 100;

  const points = data.map((point, i) => ({
    point,
    xPct: xPct(i),
    yPct: yPctFromBottom(Number(point.total_amount)),
  }));

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.xPct} ${100 - p.yPct}`)
    .join(" ");
  const areaPath = `${linePath} L ${points[points.length - 1].xPct} 100 L ${points[0].xPct} 100 Z`;

  const hoveredPoint = hovered !== null ? points[hovered] : null;
  const lastPoint = points[points.length - 1];

  const handleMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const relX = ((event.clientX - rect.left) / rect.width) * 100;
    let nearest = 0;
    let nearestDist = Infinity;
    points.forEach((p, i) => {
      const dist = Math.abs(p.xPct - relX);
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = i;
      }
    });
    setHovered(nearest);
  };

  return (
    <div className="chart-root">
      <div
        className="chart-plot"
        style={{ height: CHART_HEIGHT }}
        onMouseMove={handleMove}
        onMouseLeave={() => setHovered(null)}
      >
        {ticks.map((tick) => (
          <div key={tick} className="chart-gridline" style={{ bottom: `${(tick / niceMax) * 100}%` }}>
            <span className="chart-tick-label">{formatCompact(tick)}</span>
          </div>
        ))}

        {hoveredPoint && (
          <div className="chart-crosshair" style={{ left: `${hoveredPoint.xPct}%` }} />
        )}

        <svg className="chart-line-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
          <path d={areaPath} className="chart-area-fill" />
          <path d={linePath} className="chart-line-path" vectorEffect="non-scaling-stroke" />
        </svg>

        {points.map((p, i) => (
          <div
            key={p.point.month}
            className={hovered === i ? "chart-dot chart-dot-hovered" : "chart-dot"}
            style={{ left: `${p.xPct}%`, bottom: `${p.yPct}%` }}
          />
        ))}

        <div
          className="chart-end-label"
          style={{ left: `${lastPoint.xPct}%`, bottom: `${lastPoint.yPct}%` }}
        >
          {formatAmount(Number(lastPoint.point.total_amount))}
        </div>

        {hoveredPoint && (
          <div
            className="chart-tooltip chart-tooltip--trend"
            style={{ left: `${hoveredPoint.xPct}%`, bottom: `${hoveredPoint.yPct}%` }}
          >
            <strong>{monthLabel(hoveredPoint.point.month)}</strong>
            <span>{formatAmount(Number(hoveredPoint.point.total_amount))}</span>
          </div>
        )}
      </div>

      <div className="chart-x-axis">
        {data.map((point) => (
          <div key={point.month} className="chart-x-label" style={{ width: `${100 / n}%` }}>
            {monthLabel(point.month)}
          </div>
        ))}
      </div>
    </div>
  );
}
