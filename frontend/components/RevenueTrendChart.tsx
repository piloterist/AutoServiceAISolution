"use client";

import { useState } from "react";

export type TrendPoint = {
  period: string; // "YYYY-MM-DD" - start of the bucket
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

function periodLabel(period: string, granularity: "day" | "week" | "month"): string {
  const [year, month, day] = period.split("-").map(Number);
  if (granularity === "month") return `${MONTH_LABELS[month - 1] ?? month} ${year}`;
  return `${String(day).padStart(2, "0")}.${String(month).padStart(2, "0")}`;
}

function formatCompact(value: number): string {
  if (value >= 1_000_000) return (value / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (value >= 1_000) return (value / 1_000).toFixed(0) + "K";
  return String(Math.round(value));
}

function formatAmount(value: number): string {
  return `${Math.round(value).toLocaleString("ru-RU")} ₽`;
}

// Caps how many x-axis labels render at once - a month of daily buckets
// (~30 points) would otherwise collide into an unreadable smear.
const MAX_X_LABELS = 8;

function shouldShowLabel(index: number, total: number): boolean {
  const step = Math.max(1, Math.ceil(total / MAX_X_LABELS));
  return index % step === 0 || index === total - 1;
}

const CHART_HEIGHT = 260;

/** Revenue trend for the selected period, with the previous (same-length)
 * period overlaid as a dashed line - so "is this better or worse than
 * before" reads directly off the chart instead of requiring the reader to
 * remember last period's numbers. Bucket size (day/week/month) comes from
 * the backend, which auto-detects it from how long the selected period is
 * (see work_order_query_service.trend_summary). */
export function RevenueTrendChart({
  current,
  previous,
  granularity,
}: {
  current: TrendPoint[];
  previous: TrendPoint[];
  granularity: "day" | "week" | "month";
}) {
  const [hovered, setHovered] = useState<number | null>(null);

  if (current.length === 0) {
    return <p className="chart-empty">Нет данных за выбранный период.</p>;
  }

  const currentValues = current.map((p) => Number(p.total_amount));
  const previousValues = previous.map((p) => Number(p.total_amount));
  const maxValue = Math.max(...currentValues, ...previousValues, 1);
  const niceMax = Math.ceil(maxValue / 4) * 4 || 1;
  const ticks = [0, niceMax / 2, niceMax];

  const n = current.length;
  const xPct = (i: number) => (n === 1 ? 50 : (i / (n - 1)) * 100);
  const yPct = (value: number) => (value / niceMax) * 100;

  const currentPoints = current.map((point, i) => ({
    point,
    xPct: xPct(i),
    yPct: yPct(Number(point.total_amount)),
  }));
  // Aligned by bucket index against the current period, not by date - the
  // two periods cover different calendar dates by definition. Clipped to
  // `n` in case the two same-length periods still produced a bucket-count
  // mismatch at a week/month boundary.
  const previousPoints = previous.slice(0, n).map((point, i) => ({
    point,
    xPct: xPct(i),
    yPct: yPct(Number(point.total_amount)),
  }));

  const pathFor = (points: { xPct: number; yPct: number }[]) =>
    points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.xPct} ${100 - p.yPct}`).join(" ");

  const currentLine = pathFor(currentPoints);
  const previousLine = previousPoints.length > 1 ? pathFor(previousPoints) : "";
  const areaPath = `${currentLine} L ${currentPoints[n - 1].xPct} 100 L ${currentPoints[0].xPct} 100 Z`;

  const hoveredCurrent = hovered !== null ? currentPoints[hovered] : null;
  const hoveredPrevious = hovered !== null ? (previousPoints[hovered] ?? null) : null;
  const lastPoint = currentPoints[n - 1];

  const handleMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const relX = ((event.clientX - rect.left) / rect.width) * 100;
    let nearest = 0;
    let nearestDist = Infinity;
    currentPoints.forEach((p, i) => {
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
      {previousLine && (
        <div className="chart-legend-line">
          <span className="chart-legend-item">
            <span className="chart-legend-key chart-legend-key-current" />
            Текущий период
          </span>
          <span className="chart-legend-item">
            <span className="chart-legend-key chart-legend-key-previous" />
            Предыдущий период
          </span>
        </div>
      )}

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

        {hoveredCurrent && (
          <div className="chart-crosshair" style={{ left: `${hoveredCurrent.xPct}%` }} />
        )}

        <svg className="chart-line-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
          <path d={areaPath} className="chart-area-fill" />
          {previousLine && (
            <path
              d={previousLine}
              className="chart-line-path chart-line-path-previous"
              vectorEffect="non-scaling-stroke"
            />
          )}
          <path d={currentLine} className="chart-line-path" vectorEffect="non-scaling-stroke" />
        </svg>

        {currentPoints.map((p, i) => (
          <div
            key={p.point.period}
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

        {hoveredCurrent && (
          <div
            className="chart-tooltip chart-tooltip--trend"
            style={{ left: `${hoveredCurrent.xPct}%`, bottom: `${hoveredCurrent.yPct}%` }}
          >
            <strong>{periodLabel(hoveredCurrent.point.period, granularity)}</strong>
            <span>{formatAmount(Number(hoveredCurrent.point.total_amount))}</span>
            {hoveredPrevious && (
              <span className="chart-tooltip-muted">
                пред.: {formatAmount(Number(hoveredPrevious.point.total_amount))}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="chart-x-axis">
        {current.map((point, i) => (
          <div key={point.period} className="chart-x-label" style={{ width: `${100 / n}%` }}>
            {shouldShowLabel(i, n) ? periodLabel(point.period, granularity) : ""}
          </div>
        ))}
      </div>
    </div>
  );
}
