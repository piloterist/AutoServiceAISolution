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

function formatAmount(value: number): string {
  if (value >= 1_000_000) return (value / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (value >= 1_000) return (value / 1_000).toFixed(0) + "K";
  return String(Math.round(value));
}

const CHART_HEIGHT = 220;
const BAR_MAX_WIDTH = 24;
const BAR_GAP = 2;

export function MonthlyRevenueChart({ data }: { data: MonthlyPoint[] }) {
  const [hovered, setHovered] = useState<number | null>(null);

  if (data.length === 0) {
    return <p className="chart-empty">Нет данных за выбранный период.</p>;
  }

  const values = data.map((d) => Number(d.total_amount));
  const maxValue = Math.max(...values, 1);

  // Clean-ish y-axis ticks: 0, half, max (rounded up to a nice step).
  const niceMax = Math.ceil(maxValue / 4) * 4 || 1;
  const ticks = [0, niceMax / 2, niceMax];

  const slotWidth = 100 / data.length; // percent
  const barWidth = Math.min(BAR_MAX_WIDTH, slotWidth * 3); // px cap enforced via CSS max-width

  return (
    <div className="chart-root">
      <div className="chart-plot" style={{ height: CHART_HEIGHT }}>
        {ticks.map((tick) => (
          <div
            key={tick}
            className="chart-gridline"
            style={{ bottom: `${(tick / niceMax) * 100}%` }}
          >
            <span className="chart-tick-label">{formatAmount(tick)}</span>
          </div>
        ))}

        <div className="chart-bars">
          {data.map((point, index) => {
            const amount = Number(point.total_amount);
            const heightPct = (amount / niceMax) * 100;
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
                    <span>{amount.toLocaleString("ru-RU")} ₽</span>
                    <span className="chart-tooltip-muted">
                      {point.work_order_count}{" "}
                      {point.work_order_count === 1 ? "заказ-наряд" : "заказ-нарядов"}
                    </span>
                  </div>
                )}
                <div
                  className={isHovered ? "chart-bar chart-bar-hovered" : "chart-bar"}
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
