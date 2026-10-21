"use client";

import { useRouter } from "next/navigation";

import type { ReceivablesAging, ReceivablesAgingBucket, ReceivablesAgingRow } from "@/lib/backend-api";

const BUCKETS: { key: ReceivablesAgingBucket; label: string }[] = [
  { key: "lt_10", label: "< 10" },
  { key: "d10_30", label: "10…30" },
  { key: "d30_60", label: "30…60" },
  { key: "d60_90", label: "60…90" },
  { key: "gte_90", label: "90+" },
];

function formatDateOrDash(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ru-RU", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function formatAmount(value: string): string {
  const n = Number(value);
  if (Number.isNaN(n) || n === 0) return "";
  return n.toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}

function bucketCellClass(key: ReceivablesAgingBucket): string {
  return key === "d60_90" || key === "gte_90"
    ? "receivables-td-bucket receivables-td-bucket--overdue"
    : "receivables-td-bucket";
}

export function ReceivablesAgingView({ data }: { data: ReceivablesAging }) {
  const router = useRouter();

  return (
    <div className="card receivables-card">
      <div className="receivables-toolbar">
        <span className="admin-hint">На {formatDateOrDash(data.as_of)}</span>
      </div>

      <div className="budget-scroll">
        <table className="receivables-table">
          <thead>
            <tr>
              <th className="receivables-th-number">Заказ-наряд</th>
              <th className="receivables-th-status">Статус</th>
              <th className="receivables-th-customer">Контрагент</th>
              <th className="receivables-th-date">Дата закрытия</th>
              {BUCKETS.map((bucket) => (
                <th key={bucket.key} className="receivables-th-bucket">
                  {bucket.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row: ReceivablesAgingRow) => (
              <tr
                key={row.work_order_id}
                className="receivables-row"
                onClick={() => router.push(`/work-orders/${row.work_order_id}`)}
              >
                <td className="receivables-td-number">{row.work_order_number}</td>
                <td className="receivables-td-status">{row.status ?? "—"}</td>
                <td className="receivables-td-customer">{row.customer_name ?? "—"}</td>
                <td className="receivables-td-date">{formatDateOrDash(row.closed_date)}</td>
                {BUCKETS.map((bucket) => (
                  <td key={bucket.key} className={bucketCellClass(bucket.key)}>
                    {bucket.key === row.bucket ? formatAmount(row.debt_amount) : ""}
                  </td>
                ))}
              </tr>
            ))}
            {data.rows.length === 0 && (
              <tr>
                <td className="receivables-td-empty" colSpan={4 + BUCKETS.length}>
                  Нет заказ-нарядов с дебиторской задолженностью
                </td>
              </tr>
            )}
          </tbody>
          {data.rows.length > 0 && (
            <tfoot>
              <tr className="receivables-row receivables-row--totals">
                <td className="receivables-td-number" colSpan={4}>
                  Итого
                </td>
                {BUCKETS.map((bucket) => (
                  <td key={bucket.key} className={bucketCellClass(bucket.key)}>
                    {formatAmount(data.totals[bucket.key])}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}
