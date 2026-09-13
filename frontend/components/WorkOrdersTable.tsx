"use client";

import { useMemo, useState } from "react";

import type { WorkOrderListItem } from "@/lib/backend-api";

function formatDate(iso: string): string {
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

type Row = {
  item: WorkOrderListItem;
  date: string;
  number: string;
  vehicle: string;
  customer: string;
  status: string;
  department: string;
  amount: string;
};

type ColumnKey = "date" | "number" | "vehicle" | "customer" | "status" | "department" | "amount";

const COLUMNS: { key: ColumnKey; label: string; numeric?: boolean }[] = [
  { key: "date", label: "Дата" },
  { key: "number", label: "Номер" },
  { key: "vehicle", label: "Автомобиль" },
  { key: "customer", label: "Контрагент" },
  { key: "status", label: "Статус" },
  { key: "department", label: "Подразделение" },
  { key: "amount", label: "Сумма", numeric: true },
];

export function WorkOrdersTable({ items }: { items: WorkOrderListItem[] }) {
  const [search, setSearch] = useState("");
  const [columnFilters, setColumnFilters] = useState<Record<ColumnKey, string>>({
    date: "",
    number: "",
    vehicle: "",
    customer: "",
    status: "",
    department: "",
    amount: "",
  });

  const rows: Row[] = useMemo(
    () =>
      items.map((item) => ({
        item,
        date: formatDate(item.document_date),
        number: item.external_number,
        vehicle: item.vehicle_description ?? "",
        customer: item.customer_name ?? "",
        status: item.status ?? "",
        department: item.department ?? "",
        amount: formatAmount(item.amount),
      })),
    [items],
  );

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

      return true;
    });
  }, [rows, search, columnFilters]);

  return (
    <div className="wide-page">
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
              {COLUMNS.map((col) => (
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
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((row) => (
              <tr key={row.item.id}>
                <td>{row.date}</td>
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
