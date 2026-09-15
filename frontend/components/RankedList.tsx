"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export type RankedItem = {
  label: string;
  value: number;
  /** Pre-formatted supporting line (order count for a department row,
   * share-of-total for a status row) - computed by the caller (a Server
   * Component can't pass a formatting function across the RSC boundary,
   * only plain data). */
  meta: string;
};

// Same fixed categorical order the old donuts used (Okabe-Ito,
// colorblind-safe) - identity encoding assigned by position, never
// repainted when the filter changes which entries are present.
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

function pluralWorkOrders(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return "заказ-наряд";
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return "заказ-наряда";
  return "заказ-нарядов";
}

function formatValue(value: number, kind: "amount" | "count"): string {
  if (kind === "amount") return `${Math.round(value).toLocaleString("ru-RU")} ₽`;
  return `${value.toLocaleString("ru-RU")} ${pluralWorkOrders(value)}`;
}

export type RankedListMode =
  /** Not clickable - plain list. */
  | "none"
  /** Clicking a row navigates to the work-orders list filtered by this
   * row's label as a `status` filter, plus the dashboard's current period
   * if set. */
  | "status-link"
  /** Clicking a row toggles it as the dashboard's department filter (single
   * select) - clicking the already-selected row clears it back to "all
   * departments". Navigates within the dashboard itself (same page,
   * different `departments` query param), preserving the current/previous
   * period params. */
  | "department-filter";

/** Ranked, horizontal-bar list - replaces the old donut charts. Reads faster
 * than a donut for "who's biggest / what order": the eye compares bar
 * length top-to-bottom instead of guessing at wedge angles. */
export function RankedList({
  data,
  kind,
  mode = "none",
  dateFrom,
  dateTo,
  prevDateFrom,
  prevDateTo,
  selectedDepartments,
}: {
  data: RankedItem[];
  kind: "amount" | "count";
  mode?: RankedListMode;
  dateFrom?: string;
  dateTo?: string;
  /** Only needed for `mode="department-filter"` - carried along so toggling
   * the department filter doesn't drop the period comparison the operator
   * already set up. */
  prevDateFrom?: string;
  prevDateTo?: string;
  /** Only needed for `mode="department-filter"` - which row (if any) is the
   * active filter, so it can be highlighted and toggled back off. */
  selectedDepartments?: string[];
}) {
  const router = useRouter();
  const [grown, setGrown] = useState(false);

  // One-shot grow-in on mount: render bars at 0 width, then flip to their
  // real width on the next frame so the CSS transition actually animates
  // instead of snapping straight to full size.
  useEffect(() => {
    const raf = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  if (data.length === 0) {
    return <p className="chart-empty">Нет данных за выбранный период.</p>;
  }

  const max = Math.max(...data.map((item) => item.value), 1);
  const clickable = mode !== "none";

  const goToStatus = (status: string) => {
    const params = new URLSearchParams();
    params.set("status", status);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    router.push(`/work-orders?${params.toString()}`);
  };

  const isSelectedDepartment = (label: string) =>
    selectedDepartments?.length === 1 && selectedDepartments[0] === label;

  const toggleDepartment = (label: string) => {
    const params = new URLSearchParams();
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (prevDateFrom) params.set("prev_date_from", prevDateFrom);
    if (prevDateTo) params.set("prev_date_to", prevDateTo);
    if (!isSelectedDepartment(label)) params.set("departments", label);
    router.push(`/dashboard?${params.toString()}`);
  };

  const handleActivate = (label: string) => {
    if (mode === "status-link") goToStatus(label);
    else if (mode === "department-filter") toggleDepartment(label);
  };

  return (
    <ul className="rank-list">
      {data.map((item, index) => {
        const color = CATEGORICAL_COLORS[index % CATEGORICAL_COLORS.length];
        const pct = (item.value / max) * 100;
        const active = mode === "department-filter" && isSelectedDepartment(item.label);

        return (
          <li
            key={item.label}
            className={
              clickable
                ? active
                  ? "rank-row rank-row-clickable rank-row-active"
                  : "rank-row rank-row-clickable"
                : "rank-row"
            }
            onClick={clickable ? () => handleActivate(item.label) : undefined}
            role={clickable ? "button" : undefined}
            tabIndex={clickable ? 0 : undefined}
            aria-pressed={mode === "department-filter" ? active : undefined}
            onKeyDown={
              clickable
                ? (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      handleActivate(item.label);
                    }
                  }
                : undefined
            }
          >
            <div className="rank-line1">
              <span className="rank-name">
                <span className="rank-swatch" style={{ background: color }} />
                <span className="rank-name-text">{item.label}</span>
              </span>
              <span className="rank-value">{formatValue(item.value, kind)}</span>
            </div>
            <div className="rank-track">
              <div
                className="rank-fill"
                style={{ background: color, width: grown ? `${pct}%` : "0%" }}
              />
            </div>
            <div className="rank-meta">{item.meta}</div>
          </li>
        );
      })}
    </ul>
  );
}
