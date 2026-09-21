"use client";

import { useState } from "react";

import { DateInput } from "@/components/DateInput";
import { previousPeriod } from "@/lib/period";

// Plain GET form (no onSubmit handler - native browser navigation on
// submit reads whatever's currently in the inputs) that navigates to
// /dashboard?date_from=...&date_to=...&prev_date_from=...&prev_date_to=...,
// which the dashboard page (a Server Component) reads via searchParams.
// "use client" only for the previous-period auto-fill behavior below -
// department selection now happens by clicking a row in the department
// ranked list (see RankedList's "department-filter" mode), not here, so a
// hidden field just carries whatever department is currently selected
// through when the operator changes the date range.
//
// Sits directly beside the logo in the page header (see
// app/dashboard/page.tsx) - deliberately compact (two stacked one-line
// period rows, not a boxed card) rather than a wide standalone filter bar.
export function DashboardFilters({
  dateFrom,
  dateTo,
  prevDateFrom,
  prevDateTo,
  selectedDepartment,
  hasActiveFilters,
}: {
  /** Pre-filled into the date inputs - the dashboard defaults these when
   * the URL has no explicit params (see app/dashboard/page.tsx), so these
   * are the *effective* period, not necessarily what's literally in the
   * URL. */
  dateFrom?: string;
  dateTo?: string;
  prevDateFrom?: string;
  prevDateTo?: string;
  /** Carried through as a hidden field so submitting a new date range
   * doesn't silently drop the department filter set by clicking a row in
   * the department ranked list. */
  selectedDepartment?: string;
  /** Whether the URL itself carries an explicit filter - distinct from
   * `dateFrom`/`dateTo` being set, since those are always set (defaulted).
   * Controls whether "Сбросить фильтры" shows: it shouldn't appear on the
   * plain default view, only once the operator has actually changed
   * something. */
  hasActiveFilters: boolean;
}) {
  const [currentFrom, setCurrentFrom] = useState(dateFrom ?? "");
  const [currentTo, setCurrentTo] = useState(dateTo ?? "");
  const [prevFrom, setPrevFrom] = useState(prevDateFrom ?? "");
  const [prevTo, setPrevTo] = useState(prevDateTo ?? "");
  // Once the operator edits the previous-period fields themselves, stop
  // overwriting their choice when the current period changes.
  const [prevTouched, setPrevTouched] = useState(false);

  const recomputePrev = (from: string, to: string) => {
    if (prevTouched || !from || !to) return;
    const next = previousPeriod(from, to);
    setPrevFrom(next.dateFrom);
    setPrevTo(next.dateTo);
  };

  return (
    <form className="filters-form-row" method="get">
      {selectedDepartment && <input type="hidden" name="departments" value={selectedDepartment} />}

      <div className="filters-periods-stack">
        <div className="filters-inline-row">
          <span className="filters-inline-label">Текущий период</span>
          <span className="filters-inline-sublabel">С</span>
          <DateInput
            name="date_from"
            value={currentFrom}
            onChange={(iso) => {
              setCurrentFrom(iso);
              recomputePrev(iso, currentTo);
            }}
          />
          <span className="filters-inline-sublabel">По</span>
          <DateInput
            name="date_to"
            value={currentTo}
            onChange={(iso) => {
              setCurrentTo(iso);
              recomputePrev(currentFrom, iso);
            }}
          />
        </div>

        <div className="filters-inline-row">
          <span className="filters-inline-label">Предыдущий период</span>
          <span className="filters-inline-sublabel">С</span>
          <DateInput
            name="prev_date_from"
            value={prevFrom}
            onChange={(iso) => {
              setPrevTouched(true);
              setPrevFrom(iso);
            }}
          />
          <span className="filters-inline-sublabel">По</span>
          <DateInput
            name="prev_date_to"
            value={prevTo}
            onChange={(iso) => {
              setPrevTouched(true);
              setPrevTo(iso);
            }}
          />
        </div>
      </div>

      <div className="filters-actions">
        <button type="submit" className="filters-submit">
          Применить
        </button>
        {hasActiveFilters && (
          <a href="/dashboard" className="filters-reset">
            Сбросить фильтры
          </a>
        )}
      </div>
    </form>
  );
}
