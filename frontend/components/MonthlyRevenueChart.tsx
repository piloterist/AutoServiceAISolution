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

function pluralWorkOrders(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return "заказ-наряд";
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return "заказ-наряда";
  return "заказ-нарядов";
}

function formatAmount(value: number): string {
  return `${value.toLocaleString("ru-RU")} ₽`;
}

function formatCount(value: number): string {
  return `${value} ${pluralWorkOrders(value)}`;
}

const CHART_HEIGHT = 220;
const BAR_MAX_WIDTH = 24;

export type MonthlyBarChartProps = {
  data: MonthlyPoint[];
  /** Which field this chart plots - all formatting/value-extraction logic
   * lives inside this client component (not passed in as props): a Server
   * Component parent cannot pass functions across the server/client
   * boundary, only serializable data like this string. */
  metric: "amount" | "count";
  /** Sequential hue slot - each simultaneously-shown chart on a page should
   * get its own slot per the dataviz method (first chart -> "series",
   * second -> "series-2", etc.), never re-cycling the same hue for a
   * different measure shown at the same time. */
  colorSlot?: "series" | "series-2";
};

export function MonthlyBarChart({ data, metric, colorSlot = "series" }: MonthlyBarChartProps) {
  const [hovered, setHovered] = useState<number | null>(null);

  if (data.length === 0) {
    return <p className="chart-empty">Нет данных за выбранный период.</p>;
  }

  const getValue = (point: MonthlyPoint) =>
    metric === "amount" ? Number(point.total_amount) : point.work_order_count;
  const formatTooltipValue = (point: MonthlyPoint) =>
    metric === "amount" ? formatAmount(Number(point.total_amount)) : formatCount(point.work_order_count);
  const formatTooltipDetail = (point: MonthlyPoint) =>
    metric === "amount" ? formatCount(point.work_order_count) : formatAmount(Number(point.total_amount));

  const values = data.map(getValue);
  const maxValue = Math.max(...values, 1);

  // Clean-ish y-axis ticks: 0, half, max (rounded up to a nice step).
  const niceMax = Math.ceil(maxValue / 4) * 4 || 1;
  const ticks = [0, niceMax / 2, niceMax];

  const slotWidth = 100 / data.length; // percent
  const barWidth = Math.min(BAR_MAX_WIDTH, slotWidth * 3); // px cap enforced via CSS max-width
  const barClassName = colorSlot === "series-2" ? "chart-bar chart-bar-series-2" : "chart-bar";

  return (
    <div className="chart-root">
      <div className="chart-plot" style={{ height: CHART_HEIGHT }}>
        {ticks.map((tick) => (
          <div
            key={tick}
            className="chart-gridline"
            style={{ bottom: `${(tick / niceMax) * 100}%` }}
          >
            <span className="chart-tick-label">{formatCompact(tick)}</span>
          </div>
        ))}

        <div className="chart-bars">
          {data.map((point, index) => {
            const value = getValue(point);
            const heightPct = (value / niceMax) * 100;
            const isHovered = hovered === index;

            return (
              <div
                key={point.month}
                className="chart-bar-slot"
                style={{ width: `${slotWidth}%` }}
                onMouseEnter={() => setHovered(index)}
                onMouseLeave={() => setHovered((current) => (current === index ? null : current))}
              >
                {isHovered && (
                  <div className="chart-tooltip">
                    <strong>{monthLabel(point.month)}</strong>
                    <span>{formatTooltipValue(point)}</span>
                    <span className="chart-tooltip-muted">{formatTooltipDetail(point)}</span>
                  </div>
                )}
                <div
                  className={isHovered ? `${barClassName} chart-bar-hovered` : barClassName}
                  style={{ height: `${heightPct}%`, maxWidth: barWidth }}
                />
              </div>
            );
          })}
        </div>
      </div>

      <div className="chart-x-axis">
        {data.map((point) => (
          <div key={point.month} className="chart-x-label" style={{ width: `${slotWidth}%` }}>
            {monthLabel(point.month)}
          </div>
        ))}
      </div>
    </div>
  );
}
