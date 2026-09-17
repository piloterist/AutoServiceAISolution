"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import type { WorkOrderListItem } from "@/lib/backend-api";

function formatDateOrDash(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ru-RU", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function formatAmount(amount: string | number): string {
  const value = typeof amount === "string" ? Number(amount) : amount;
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value) + " ₽";
}

function formatAmountOrDash(amount: string | null): string {
  if (amount === null) return "—";
  return formatAmount(amount);
}

/** 0% and "no payment data at all" (null) both mean "no payment" - shown
 * identically as "—" instead of some rows reading "0%" and others "—" for
 * the same underlying state. Doesn't affect matchesPaymentFilter below,
 * which already treats null as 0. */
function formatPercentOrDash(percent: string | null): string {
  if (percent === null || Number(percent) === 0) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(percent)) + "%";
}

type PaymentFilter = "all" | "full" | "partial" | "none";

/** "Оплата" filter categories, derived from the same payment_percent 5S
 * AUTO already computes (see WorkOrderListItem) - not a new calculation.
 * A null payment_percent (no payment data from 1C yet) counts as "Без
 * оплаты", same as an explicit 0. */
function matchesPaymentFilter(percent: string | null, filter: PaymentFilter): boolean {
  if (filter === "all") return true;
  const value = percent === null ? 0 : Number(percent);
  if (filter === "none") return value <= 0;
  if (filter === "partial") return value > 0 && value < 100;
  return value >= 100; // "full"
}

/** `iso` falls within [dateFrom, dateTo] - dateTo is treated as inclusive of
 * that whole day (a plain <input type="date"> picker gives no time
 * component, and "по 13.09" should include everything on the 13th). A null
 * `iso` (not closed yet) never matches an active range - there's no date to
 * fall inside it. */
function isWithinDateRange(iso: string | null, dateFrom: string, dateTo: string): boolean {
  if (!dateFrom && !dateTo) return true;
  if (!iso) return false;

  const orderTime = new Date(iso).getTime();

  if (dateFrom) {
    const fromTime = new Date(dateFrom).getTime();
    if (!Number.isNaN(fromTime) && orderTime < fromTime) return false;
  }

  if (dateTo) {
    const toTime = new Date(dateTo).getTime() + 24 * 60 * 60 * 1000;
    if (!Number.isNaN(toTime) && orderTime >= toTime) return false;
  }

  return true;
}

type Row = {
  item: WorkOrderListItem;
  createdDate: string;
  closedDate: string;
  number: string;
  vehicle: string;
  customer: string;
  status: string;
  department: string;
  repairType: string;
  amount: string;
  paidAmount: string;
  paymentPercent: string;
};

type ColumnKey =
  | "createdDate"
  | "closedDate"
  | "number"
  | "vehicle"
  | "customer"
  | "status"
  | "department"
  | "repairType"
  | "amount"
  | "paidAmount"
  | "paymentPercent";

const COLUMNS: { key: ColumnKey; label: string; numeric?: boolean }[] = [
  { key: "createdDate", label: "Дата создания" },
  { key: "closedDate", label: "Дата закрытия" },
  { key: "number", label: "Номер" },
  { key: "vehicle", label: "Автомобиль" },
  { key: "customer", label: "Контрагент" },
  { key: "status", label: "Статус" },
  { key: "department", label: "Подразделение" },
  { key: "repairType", label: "Вид ремонта" },
  { key: "amount", label: "Сумма", numeric: true },
  { key: "paidAmount", label: "Сумма оплаты", numeric: true },
  { key: "paymentPercent", label: "% оплаты", numeric: true },
];

/** Plain numeric string for spreadsheet paste (no "₽"/"%"/thousands
 * separators) - Excel/Sheets only recognize a pasted cell as a real number
 * when it looks like one, not when it's pre-formatted for display. */
function exportNumber(value: string | null): string {
  if (value === null) return "";
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : "";
}

/** Tab-separated export of the currently visible rows (header + one line
 * per row), for pasting straight into Excel/Sheets as real columns. Dates
 * and text stay exactly as shown on screen (Excel's RU locale reads
 * "dd.mm.yyyy" as a real date); amounts/percent are re-derived from the
 * raw values instead of the display strings, since those carry a "₽"/"%"/
 * thousands separators that would paste as text, not numbers. */
function buildClipboardText(rows: Row[]): string {
  const header = COLUMNS.map((col) => col.label).join("\t");
  const lines = rows.map((row) =>
    [
      row.createdDate,
      row.closedDate,
      row.number,
      row.vehicle || "—",
      row.customer || "—",
      row.status || "—",
      row.department || "—",
      row.repairType || "—",
      exportNumber(row.item.amount),
      exportNumber(row.item.paid_amount),
      exportNumber(row.item.payment_percent),
    ].join("\t"),
  );
  return [header, ...lines].join("\n");
}

export function WorkOrdersTable({
  items,
  initialStatus,
  initialDateFrom,
  initialDateTo,
  initialClosedFrom,
  initialClosedTo,
  initialDepartment,
  paidFrom,
  paidTo,
}: {
  items: WorkOrderListItem[];
  /** Pre-applied filters, e.g. arriving from a click on the dashboard's
   * status chips (/work-orders?status=...&date_from=...&date_to=...) or the
   * revenue stat tile
   * (/work-orders?closed_from=...&closed_to=...&departments=...). Plain
   * strings from the URL's searchParams, not component state shared across
   * pages - just the initial values. */
  initialStatus?: string;
  initialDateFrom?: string;
  initialDateTo?: string;
  initialClosedFrom?: string;
  initialClosedTo?: string;
  initialDepartment?: string;
  /** Set when `items` already arrived pre-filtered by real payment date
   * (the dashboard's "Оплаты за период" tile) - unlike the other initial*
   * filters above, this one was applied server-side (see
   * app/work-orders/page.tsx), so it's only used here to show a banner,
   * not to filter `rows` again. */
  paidFrom?: string;
  paidTo?: string;
}) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [columnFilters, setColumnFilters] = useState<Record<ColumnKey, string>>({
    createdDate: "",
    closedDate: "",
    number: "",
    vehicle: "",
    customer: "",
    status: "",
    department: initialDepartment ?? "",
    repairType: "",
    amount: "",
    paidAmount: "",
    paymentPercent: "",
  });
  // Status has its own checkbox dropdown (below) instead of the generic
  // per-column text filter every other column gets - a free-text substring
  // match makes little sense against a small fixed set of status values.
  const [selectedStatuses, setSelectedStatuses] = useState<string[]>(
    initialStatus ? [initialStatus] : [],
  );
  const [dateFrom, setDateFrom] = useState(initialDateFrom ?? "");
  const [dateTo, setDateTo] = useState(initialDateTo ?? "");
  const [closedFrom, setClosedFrom] = useState(initialClosedFrom ?? "");
  const [closedTo, setClosedTo] = useState(initialClosedTo ?? "");
  const [paymentFilter, setPaymentFilter] = useState<PaymentFilter>("all");

  const rows: Row[] = useMemo(
    () =>
      items.map((item) => ({
        item,
        createdDate: formatDateOrDash(item.created_date),
        closedDate: formatDateOrDash(item.closed_date),
        number: item.external_number,
        vehicle: item.vehicle_description ?? "",
        customer: item.customer_name ?? "",
        status: item.status ?? "",
        department: item.department ?? "",
        repairType: item.repair_type ?? "",
        amount: formatAmount(item.amount),
        paidAmount: formatAmountOrDash(item.paid_amount),
        paymentPercent: formatPercentOrDash(item.payment_percent),
      })),
    [items],
  );

  // Distinct status values actually present in the data - never a
  // hardcoded list of statuses (see ARCHITECTURE.md).
  const availableStatuses = useMemo(() => {
    const values = new Set<string>();
    for (const item of items) {
      if (item.status) values.add(item.status);
    }
    return Array.from(values).sort((a, b) => a.localeCompare(b, "ru"));
  }, [items]);

  const toggleStatus = (status: string) => {
    setSelectedStatuses((prev) =>
      prev.includes(status) ? prev.filter((value) => value !== status) : [...prev, status],
    );
  };

  const filteredRows = useMemo(() => {
    const query = search.trim().toLowerCase();

    return rows.filter((row) => {
      if (query) {
        const haystack = COLUMNS.map((col) => row[col.key])
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(query)) return false;
      }

      for (const { key } of COLUMNS) {
        const filterValue = columnFilters[key].trim().toLowerCase();
        if (filterValue && !row[key].toLowerCase().includes(filterValue)) return false;
      }

      // No status checked = show all statuses (same "empty = all" rule
      // used by the department filter on the dashboard).
      if (selectedStatuses.length > 0 && !selectedStatuses.includes(row.item.status ?? "")) {
        return false;
      }

      if (!isWithinDateRange(row.item.document_date, dateFrom, dateTo)) return false;
      if (!isWithinDateRange(row.item.closed_date, closedFrom, closedTo)) return false;
      if (!matchesPaymentFilter(row.item.payment_percent, paymentFilter)) return false;

      return true;
    });
  }, [
    rows,
    search,
    columnFilters,
    selectedStatuses,
    dateFrom,
    dateTo,
    closedFrom,
    closedTo,
    paymentFilter,
  ]);

  // Recomputes with filteredRows - the whole point is that it tracks
  // whatever's currently visible, not the unfiltered total.
  const filteredAmount = useMemo(
    () => filteredRows.reduce((sum, row) => sum + Number(row.item.amount), 0),
    [filteredRows],
  );

  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(buildClipboardText(filteredRows));
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
    setTimeout(() => setCopyState("idle"), 2000);
  };

  return (
    <div className="wide-page">
      {(paidFrom || paidTo) && (
        <p className="chart-subtitle">
          Показаны заказ-наряды с оплатами за период {paidFrom || "…"} – {paidTo || "…"}
        </p>
      )}

      <div className="toolbar">
        <label className="payment-filter">
          <span className="period-filter-label">Оплата</span>
          <select
            value={paymentFilter}
            onChange={(event) => setPaymentFilter(event.target.value as PaymentFilter)}
            aria-label="Фильтр по оплате"
          >
            <option value="all">Все</option>
            <option value="full">Полная оплата</option>
            <option value="partial">Частичная оплата</option>
            <option value="none">Без оплаты</option>
          </select>
        </label>

        <details className="status-filter">
          <summary>
            Статус{selectedStatuses.length > 0 ? ` (${selectedStatuses.length})` : ""}
          </summary>
          <div className="status-filter-panel">
            {availableStatuses.length === 0 && (
              <p className="status-filter-empty">Нет данных по статусам</p>
            )}
            {availableStatuses.map((status) => (
              <label key={status} className="status-filter-checkbox">
                <input
                  type="checkbox"
                  checked={selectedStatuses.includes(status)}
                  onChange={() => toggleStatus(status)}
                />
                {status}
              </label>
            ))}
            {selectedStatuses.length > 0 && (
              <button
                type="button"
                className="status-filter-clear"
                onClick={() => setSelectedStatuses([])}
              >
                Сбросить
              </button>
            )}
          </div>
        </details>

        <div className="period-filter">
          <span className="period-filter-label">Дата документа</span>
          <label>
            С
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
              aria-label="Дата документа с"
            />
          </label>
          <label>
            По
            <input
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
              aria-label="Дата документа по"
            />
          </label>
        </div>

        <div className="period-filter">
          <span className="period-filter-label">Дата закрытия</span>
          <label>
            С
            <input
              type="date"
              value={closedFrom}
              onChange={(event) => setClosedFrom(event.target.value)}
              aria-label="Дата закрытия с"
            />
          </label>
          <label>
            По
            <input
              type="date"
              value={closedTo}
              onChange={(event) => setClosedTo(event.target.value)}
              aria-label="Дата закрытия по"
            />
          </label>
        </div>
      </div>

      <input
        type="search"
        className="search-input"
        placeholder="Поиск по всем полям (номер, ВИН, контрагент, статус, подразделение, сумма...)"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        aria-label="Поиск по всем полям"
      />

      <div className="table-meta">
        <span>
          Показано {filteredRows.length} из {items.length}
        </span>
        <span className="table-meta-total">Сумма: {formatAmount(filteredAmount)}</span>
        <button type="button" className="copy-button" onClick={handleCopy}>
          {copyState === "copied" ? "Скопировано ✓" : copyState === "error" ? "Не удалось скопировать" : "Скопировать"}
        </button>
      </div>

      <div className="table-wrap">
        <table className="data-table data-table--work-orders">
          <thead>
            <tr>
              {COLUMNS.map((col) => (
                <th key={col.key} className={col.numeric ? "num" : undefined}>
                  {col.label}
                </th>
              ))}
            </tr>
            <tr className="filter-row">
              {COLUMNS.map((col) =>
                col.key === "status" ? (
                  <th key={col.key} />
                ) : (
                  <th key={col.key} className={col.numeric ? "num" : undefined}>
                    <input
                      type="text"
                      value={columnFilters[col.key]}
                      onChange={(event) =>
                        setColumnFilters((prev) => ({ ...prev, [col.key]: event.target.value }))
                      }
                      placeholder="Фильтр"
                      aria-label={`Фильтр по полю ${col.label}`}
                    />
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((row) => (
              <tr
                key={row.item.id}
                className="row-clickable"
                role="link"
                tabIndex={0}
                onClick={() => router.push(`/work-orders/${row.item.id}`)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    router.push(`/work-orders/${row.item.id}`);
                  }
                }}
              >
                <td>{row.createdDate}</td>
                <td>{row.closedDate}</td>
                <td>{row.number}</td>
                <td>{row.vehicle || "—"}</td>
                <td>{row.customer || "—"}</td>
                <td>{row.status || "—"}</td>
                <td>{row.department || "—"}</td>
                <td>{row.repairType || "—"}</td>
                <td className="num">{row.amount}</td>
                <td className="num">{row.paidAmount}</td>
                <td className="num">{row.paymentPercent}</td>
              </tr>
            ))}
            {filteredRows.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} className="table-empty">
                  Ничего не найдено.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
