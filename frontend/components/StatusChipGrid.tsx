"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export type StatusChipItem = {
  label: string;
  value: number;
  meta: string;
};

// Same fixed categorical order used elsewhere on the dashboard (Okabe-Ito,
// colorblind-safe) - identity encoding assigned by position.
const CATEGORICAL_COLORS = [
  "#0072B2",
  "#E69F00",
  "#009E73",
  "#CC79A7",
  "#D55E00",
  "#56B4E9",
  "#F0E442",
  "#8c8c8c",
];

/** A wrapping grid of status "chips" - each a small tile with a count, a
 * share-of-total meter, and its own accent color, rather than another
 * ranked list. Reads as a mosaic at a glance (how many statuses, how lopsided
 * the distribution is) instead of a scan-down-the-rows list, which suits a
 * dimension with no inherent "biggest is most important" ordering the way
 * department revenue has. Clicking a chip filters the work-orders list by
 * that status, same as the department/status ranked lists elsewhere. */
export function StatusChipGrid({
  data,
  dateFrom,
  dateTo,
}: {
  data: StatusChipItem[];
  dateFrom?: string;
  dateTo?: string;
}) {
  const router = useRouter();
  const [grown, setGrown] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  if (data.length === 0) {
    return <p className="chart-empty">Нет данных за выбранный период.</p>;
  }

  const max = Math.max(...data.map((item) => item.value), 1);

  const goToStatus = (status: string) => {
    const params = new URLSearchParams();
    params.set("status", status);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    router.push(`/work-orders?${params.toString()}`);
  };

  return (
    <div className="status-chip-grid">
      {data.map((item, index) => {
        const color = CATEGORICAL_COLORS[index % CATEGORICAL_COLORS.length];
        const pct = (item.value / max) * 100;

        return (
          <button
            key={item.label}
            type="button"
            className="status-chip"
            style={{ "--chip-color": color } as React.CSSProperties}
            onClick={() => goToStatus(item.label)}
          >
            <span className="status-chip-top">
              <span className="status-chip-dot" />
              <span className="status-chip-label">{item.label}</span>
            </span>
            <span className="status-chip-value">{item.value.toLocaleString("ru-RU")}</span>
            <span className="status-chip-meta">{item.meta}</span>
            <span className="status-chip-track">
              <span className="status-chip-fill" style={{ width: grown ? `${pct}%` : "0%" }} />
            </span>
          </button>
        );
      })}
    </div>
  );
}
