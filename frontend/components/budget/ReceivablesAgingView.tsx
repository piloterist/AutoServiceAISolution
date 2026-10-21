"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { DateInput } from "@/components/DateInput";
import type { ReceivablesAging, ReceivablesAgingBucket, ReceivablesAgingRow } from "@/lib/backend-api";

const BUCKETS: { key: ReceivablesAgingBucket; label: string }[] = [
  { key: "lt_10", label: "< 10" },
  { key: "d10_30", label: "10…30" },
  { key: "d30_60", label: "30…60" },
  { key: "d60_90", label: "60…90" },
  { key: "gte_90", label: "90+" },
];

// Заказ-наряд, Дата закрытия, Дата счета, Статус, Контрагент, Дни - the
// identifying columns before the bucket columns start.
const LEADING_COLUMN_COUNT = 6;

function formatDateOrDash(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ru-RU", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function formatAmount(value: number): string {
  if (value === 0) return "";
  return value.toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}

function bucketCellClass(key: ReceivablesAgingBucket): string {
  return key === "d60_90" || key === "gte_90"
    ? "receivables-td-bucket receivables-td-bucket--overdue"
    : "receivables-td-bucket";
}

function mskMidnightUtcMs(dateStr: string): number {
  return new Date(`${dateStr}T00:00:00+03:00`).getTime();
}

/** `iso` falls within [dateFrom, dateTo] - dateTo is treated as inclusive of
 * that whole (Moscow-local) day, same reasoning/logic as WorkOrdersTable's
 * own isWithinDateRange (duplicated rather than shared - small enough, and
 * the two tables don't otherwise share a module). */
function isWithinDateRange(iso: string | null, dateFrom: string, dateTo: string): boolean {
  if (!dateFrom && !dateTo) return true;
  if (!iso) return false;

  const orderTime = new Date(iso).getTime();

  if (dateFrom) {
    const fromTime = mskMidnightUtcMs(dateFrom);
    if (!Number.isNaN(fromTime) && orderTime < fromTime) return false;
  }

  if (dateTo) {
    const toTime = mskMidnightUtcMs(dateTo) + 24 * 60 * 60 * 1000;
    if (!Number.isNaN(toTime) && orderTime >= toTime) return false;
  }

  return true;
}

export function ReceivablesAgingView({ data }: { data: ReceivablesAging }) {
  const router = useRouter();
  const [closedFrom, setClosedFrom] = useState("");
  const [closedTo, setClosedTo] = useState("");
  const [onlyIndividualCustomer, setOnlyIndividualCustomer] = useState(false);

  const filteredRows = useMemo(
    () =>
      data.rows.filter(
        (row) =>
          isWithinDateRange(row.closed_date, closedFrom, closedTo) &&
          (!onlyIndividualCustomer || row.is_individual_customer),
      ),
    [data.rows, closedFrom, closedTo, onlyIndividualCustomer],
  );

  const bucketTotals = useMemo(() => {
    const totals: Record<ReceivablesAgingBucket, number> = {
      lt_10: 0,
      d10_30: 0,
      d30_60: 0,
      d60_90: 0,
      gte_90: 0,
    };
    for (const row of filteredRows) {
      totals[row.bucket] += Number(row.debt_amount);
    }
    return totals;
  }, [filteredRows]);

  return (
    <div className="card receivables-card">
      <div className="receivables-toolbar">
        <div className="period-filter">
          <span className="period-filter-label">Дата закрытия</span>
          <label>
            С
            <DateInput value={closedFrom} onChange={setClosedFrom} ariaLabel="Дата закрытия с" />
          </label>
          <label>
            По
            <DateInput value={closedTo} onChange={setClosedTo} ariaLabel="Дата закрытия по" />
          </label>
        </div>
        <label className="individual-customer-filter">
          <input
            type="checkbox"
            checked={onlyIndividualCustomer}
            onChange={(event) => setOnlyIndividualCustomer(event.target.checked)}
          />
          Физ.лицо
        </label>
        <span className="admin-hint">На {formatDateOrDash(data.as_of)}</span>
      </div>

      <div className="budget-scroll">
        <table className="receivables-table">
          <thead>
            <tr>
              <th className="receivables-th-number">Заказ-наряд</th>
              <th className="receivables-th-date">Дата закрытия</th>
              <th className="receivables-th-date">Дата счета</th>
              <th className="receivables-th-status">Статус</th>
              <th className="receivables-th-customer">Контрагент</th>
              <th className="receivables-th-days">Дни</th>
              {BUCKETS.map((bucket) => (
                <th key={bucket.key} className="receivables-th-bucket">
                  {bucket.label}
                </th>
              ))}
            </tr>
            <tr className="receivables-row receivables-row--totals">
              <td className="receivables-td-number" colSpan={LEADING_COLUMN_COUNT}>
                Итого
              </td>
              {BUCKETS.map((bucket) => (
                <td key={bucket.key} className={bucketCellClass(bucket.key)}>
                  {formatAmount(bucketTotals[bucket.key])}
                </td>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((row: ReceivablesAgingRow) => (
              <tr
                key={row.work_order_id}
                className="receivables-row"
                onClick={() => router.push(`/work-orders/${row.work_order_id}`)}
              >
                <td className="receivables-td-number">{row.work_order_number}</td>
                <td className="receivables-td-date">{formatDateOrDash(row.closed_date)}</td>
                <td className="receivables-td-date">{formatDateOrDash(row.invoice_date)}</td>
                <td className="receivables-td-status">{row.status ?? "—"}</td>
                <td className="receivables-td-customer">{row.customer_name ?? "—"}</td>
                <td className="receivables-td-days">{row.days_overdue}</td>
                {BUCKETS.map((bucket) => (
                  <td key={bucket.key} className={bucketCellClass(bucket.key)}>
                    {bucket.key === row.bucket ? formatAmount(Number(row.debt_amount)) : ""}
                  </td>
                ))}
              </tr>
            ))}
            {filteredRows.length === 0 && (
              <tr>
                <td className="receivables-td-empty" colSpan={LEADING_COLUMN_COUNT + BUCKETS.length}>
                  Нет заказ-нарядов с дебиторской задолженностью за выбранный период
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
