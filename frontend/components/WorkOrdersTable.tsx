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

function formatAmount(amount: string): string {
  const value = Number(amount);
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value) + " ₽";
}

/** document_date falls within [dateFrom, dateTo] - dateTo is treated as
 * inclusive of that whole day (a plain <input type="date"> picker gives no
 * time component, and "по 13.09" should include everything on the 13th). */
function isWithinDateRange(iso: string, dateFrom: string, dateTo: string): boolean {
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
  amount: string;
};

type ColumnKey =
  | "createdDate"
  | "closedDate"
  | "number"
  | "vehicle"
  | "customer"
  | "status"
  | "department"
  | "amount";

const COLUMNS: { key: ColumnKey; label: string; numeric?: boolean }[] = [
  { key: "createdDate", label: "Дата создания" },
  { key: "closedDate", label: "Дата закрытия" },
  { key: "number", label: "Номер" },
  { key: "vehicle", label: "Автомобиль" },
  { key: "customer", label: "Контрагент" },
  { key: "status", label: "Статус" },
  { key: "department", label: "Подразделение" },
  { key: "amount", label: "Сумма", numeric: true },
];

export function WorkOrdersTable({ items }: { items: WorkOrderListItem[] }) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [columnFilters, setColumnFilters] = useState<Record<ColumnKey, string>>({
    createdDate: "",
    closedDate: "",
    number: "",
    vehicle: "",
    customer: "",
    status: "",
    department: "",
    amount: "",
  });
  // Status has its own checkbox dropdown (below) instead of the generic
  // per-column text filter every other column gets - a free-text substring
  // match makes little sense against a small fixed set of status values.
  const [selectedStatuses, setSelectedStatuses] = useState<string[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

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
        amount: formatAmount(item.amount),
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

      return true;
    });
  }, [rows, search, columnFilters, selectedStatuses, dateFrom, dateTo]);

  return (
    <div className="wide-page">
      <div className="toolbar">
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
          <label>
            С
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
              aria-label="Период с даты"
            />
          </label>
          <label>
            По
            <input
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
              aria-label="Период по дату"
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

      <p className="table-meta">
        Показано {filteredRows.length} из {items.length}
      </p>

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
                <td className="num">{row.amount}</td>
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
