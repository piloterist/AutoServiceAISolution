"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { DateInput } from "@/components/DateInput";
import type { WorkOrderListItem } from "@/lib/backend-api";
import { getCachedWorkOrders, loadWorkOrdersCached, loadWorkOrdersFiltered } from "@/lib/work-orders-cache";

// Column widths as a CSS grid template (percentages), applied identically to
// the header row, the filter row and every virtualized body row so they
// stay aligned - see the "Virtualized Work Orders table" CSS in globals.css
// for why this is grid-per-row rather than a real <table>: a virtualizer
// has to absolutely-position each row by a computed offset, which a native
// <table>'s row-flow layout doesn't support.
// 1 Дата документа | 2 Дата закрытия | 3 Номер | 4 Автомобиль |
// 5 Контрагент | 6 Статус | 7 Внутренний | 8 Подразделение | 9 Вид ремонта |
// 10 Сумма | 11 Сумма оплаты | 12 % оплаты
const GRID_TEMPLATE_COLUMNS = "7% 7% 7% 14% 9% 7% 9% 9% 9% 7% 8% 7%";

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
type InternalFilter = "all" | "internal" | "external";

/** "Внутренний" filter, analogous to the "Оплата" select above - a plain
 * boolean, so a 3-state dropdown reads more clearly here than a
 * multi-checkbox dropdown (which fits an open set of values, like
 * "Статус"). */
function matchesInternalFilter(isInternal: boolean, filter: InternalFilter): boolean {
  if (filter === "all") return true;
  return filter === "internal" ? isInternal : !isInternal;
}

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
  documentDate: string;
  closedDate: string;
  number: string;
  vehicle: string;
  customer: string;
  status: string;
  internal: string;
  department: string;
  repairType: string;
  amount: string;
  paidAmount: string;
  paymentPercent: string;
};

type ColumnKey =
  | "documentDate"
  | "closedDate"
  | "number"
  | "vehicle"
  | "customer"
  | "status"
  | "internal"
  | "department"
  | "repairType"
  | "amount"
  | "paidAmount"
  | "paymentPercent";

const COLUMNS: { key: ColumnKey; label: string; numeric?: boolean }[] = [
  { key: "documentDate", label: "Дата документа" },
  { key: "closedDate", label: "Дата закрытия" },
  { key: "number", label: "Номер" },
  { key: "vehicle", label: "Автомобиль" },
  { key: "customer", label: "Контрагент" },
  { key: "status", label: "Статус" },
  { key: "internal", label: "Внутренний" },
  { key: "department", label: "Подразделение" },
  { key: "repairType", label: "Вид ремонта" },
  { key: "amount", label: "Сумма", numeric: true },
  { key: "paidAmount", label: "Сумма оплаты", numeric: true },
  { key: "paymentPercent", label: "% оплаты", numeric: true },
];

type PersistedFilters = {
  search: string;
  columnFilters: Record<ColumnKey, string>;
  selectedStatuses: string[];
  dateFrom: string;
  dateTo: string;
  closedFrom: string;
  closedTo: string;
  paymentFilter: PaymentFilter;
  internalFilter: InternalFilter;
};

const FILTERS_STORAGE_KEY = "work-orders-filters:v1";

/** So filters survive "open a work order, then go back" - without this,
 * every click into a row and back reset the whole toolbar, since
 * WorkOrdersTable unmounts and remounts fresh on each visit to the list
 * (see lib/work-orders-cache.ts for the same reasoning applied to the
 * loaded data itself). sessionStorage, not state lifted higher up - it
 * needs to survive a full remount, but only for this tab/session, and
 * silently no-ops server-side (SSR) and in a private-browsing tab that
 * blocks it, same as the data cache. */
function readPersistedFilters(): PersistedFilters | null {
  try {
    const raw = sessionStorage.getItem(FILTERS_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PersistedFilters) : null;
  } catch {
    return null;
  }
}

function writePersistedFilters(filters: PersistedFilters): void {
  try {
    sessionStorage.setItem(FILTERS_STORAGE_KEY, JSON.stringify(filters));
  } catch {
    // Ignore (private browsing, quota) - filters just won't survive a
    // remount this time, same degradation as the data cache.
  }
}

function clearPersistedFilters(): void {
  try {
    sessionStorage.removeItem(FILTERS_STORAGE_KEY);
  } catch {
    // ignore
  }
}

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
      row.documentDate,
      row.closedDate,
      row.number,
      row.vehicle || "—",
      row.customer || "—",
      row.status || "—",
      row.internal,
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
  initialStatus,
  initialDateFrom,
  initialDateTo,
  initialClosedFrom,
  initialClosedTo,
  initialDepartment,
  paidFrom,
  paidTo,
}: {
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
  /** Restricts to work orders with a real payment in this range (the
   * dashboard's "Оплаты за период" tile) - applied server-side by the
   * fetch itself (see lib/work-orders-cache.ts loadWorkOrdersFiltered),
   * not by filtering an already-loaded `rows` again. Also shown as a
   * banner below. */
  paidFrom?: string;
  paidTo?: string;
}) {
  const router = useRouter();

  // Loads client-side (not server-rendered) so the unfiltered case can
  // render instantly from lib/work-orders-cache.ts's cache when the
  // dashboard has already prefetched it, instead of every visit paying for
  // a fresh multi-thousand-row fetch. See WorkOrdersPrefetcher.
  const [items, setItems] = useState<WorkOrderListItem[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);

    const onProgress = (partialItems: WorkOrderListItem[], partialTotal: number) => {
      if (cancelled) return;
      setItems(partialItems);
      setTotal(partialTotal);
    };

    const hasPaidFilter = Boolean(paidFrom || paidTo);

    if (!hasPaidFilter) {
      const cached = getCachedWorkOrders();
      if (cached) {
        setItems(cached.items);
        setTotal(cached.total);
        setLoading(!cached.complete);
      } else {
        setLoading(true);
      }
    } else {
      setLoading(true);
    }

    const task = hasPaidFilter
      ? loadWorkOrdersFiltered({ paidFrom, paidTo }, onProgress)
      : loadWorkOrdersCached(onProgress);

    task
      .then((result) => {
        if (cancelled) return;
        setItems(result.items);
        setTotal(result.total);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : "Unknown error");
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [paidFrom, paidTo]);

  // A link with real filter params (e.g. a dashboard status chip or the
  // revenue tile) always wins for this visit; otherwise restore whatever
  // was last set, from sessionStorage (see readPersistedFilters above) -
  // recomputed fresh each render, but only the very first render's result
  // is ever used, since every field below only reads it inside a lazy
  // useState initializer.
  const hasUrlFilters = Boolean(
    initialStatus || initialDateFrom || initialDateTo || initialClosedFrom || initialClosedTo,
  );
  const persisted = hasUrlFilters ? null : readPersistedFilters();

  const [search, setSearch] = useState(() => persisted?.search ?? "");
  const [columnFilters, setColumnFilters] = useState<Record<ColumnKey, string>>(() => ({
    documentDate: persisted?.columnFilters.documentDate ?? "",
    closedDate: persisted?.columnFilters.closedDate ?? "",
    number: persisted?.columnFilters.number ?? "",
    vehicle: persisted?.columnFilters.vehicle ?? "",
    customer: persisted?.columnFilters.customer ?? "",
    status: "",
    internal: "",
    department: initialDepartment ?? persisted?.columnFilters.department ?? "",
    repairType: persisted?.columnFilters.repairType ?? "",
    amount: persisted?.columnFilters.amount ?? "",
    paidAmount: persisted?.columnFilters.paidAmount ?? "",
    paymentPercent: persisted?.columnFilters.paymentPercent ?? "",
  }));
  // Status has its own checkbox dropdown (below) instead of the generic
  // per-column text filter every other column gets - a free-text substring
  // match makes little sense against a small fixed set of status values.
  const [selectedStatuses, setSelectedStatuses] = useState<string[]>(
    () => (initialStatus ? [initialStatus] : persisted?.selectedStatuses ?? []),
  );
  const [dateFrom, setDateFrom] = useState(() => initialDateFrom ?? persisted?.dateFrom ?? "");
  const [dateTo, setDateTo] = useState(() => initialDateTo ?? persisted?.dateTo ?? "");
  const [closedFrom, setClosedFrom] = useState(
    () => initialClosedFrom ?? persisted?.closedFrom ?? "",
  );
  const [closedTo, setClosedTo] = useState(() => initialClosedTo ?? persisted?.closedTo ?? "");
  const [paymentFilter, setPaymentFilter] = useState<PaymentFilter>(
    () => persisted?.paymentFilter ?? "all",
  );
  const [internalFilter, setInternalFilter] = useState<InternalFilter>(
    () => persisted?.internalFilter ?? "all",
  );

  useEffect(() => {
    writePersistedFilters({
      search,
      columnFilters,
      selectedStatuses,
      dateFrom,
      dateTo,
      closedFrom,
      closedTo,
      paymentFilter,
      internalFilter,
    });
  }, [
    search,
    columnFilters,
    selectedStatuses,
    dateFrom,
    dateTo,
    closedFrom,
    closedTo,
    paymentFilter,
    internalFilter,
  ]);

  const resetFilters = () => {
    setSearch("");
    setColumnFilters({
      documentDate: "",
      closedDate: "",
      number: "",
      vehicle: "",
      customer: "",
      status: "",
      internal: "",
      department: "",
      repairType: "",
      amount: "",
      paidAmount: "",
      paymentPercent: "",
    });
    setSelectedStatuses([]);
    setDateFrom("");
    setDateTo("");
    setClosedFrom("");
    setClosedTo("");
    setPaymentFilter("all");
    setInternalFilter("all");
    clearPersistedFilters();
  };

  const rows: Row[] = useMemo(
    () =>
      items.map((item) => ({
        item,
        documentDate: formatDateOrDash(item.document_date),
        closedDate: formatDateOrDash(item.closed_date),
        number: item.external_number,
        vehicle: item.vehicle_description ?? "",
        customer: item.customer_name ?? "",
        status: item.status ?? "",
        internal: item.is_internal ? "Да" : "Нет",
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

  // A native <details> only closes on a second click on its own <summary>
  // - it has no built-in "click outside to close" behavior the way a
  // <select> dropdown does. Made controlled (open={statusFilterOpen}) so
  // an outside click can close it too, without interfering with clicking
  // the summary itself (native toggle) or checking boxes inside the panel
  // (both are inside statusFilterRef, so the outside-click check leaves
  // them alone).
  const [statusFilterOpen, setStatusFilterOpen] = useState(false);
  const statusFilterRef = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    if (!statusFilterOpen) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (statusFilterRef.current && !statusFilterRef.current.contains(event.target as Node)) {
        setStatusFilterOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [statusFilterOpen]);

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
      if (!matchesInternalFilter(row.item.is_internal, internalFilter)) return false;

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
    internalFilter,
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

  // Only the ~20-30 rows actually in view get mounted in the DOM - with
  // several thousand work orders (and growing), rendering every row at
  // once was what made the page sluggish. Filtering itself is untouched
  // (still runs over the full `rows` array above) - this only changes how
  // the *result* gets rendered. Row height is measured dynamically
  // (measureElement), not fixed, since a long "Автомобиль"/"Контрагент"
  // value can wrap to two lines.
  const scrollRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: filteredRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 46,
    overscan: 12,
  });

  if (loadError) {
    return (
      <div className="wide-page">
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {loadError}</p>
        </div>
      </div>
    );
  }

  if (loading && items.length === 0) {
    return (
      <div className="wide-page">
        <p className="table-empty">Загрузка заказ-нарядов…</p>
      </div>
    );
  }

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

        <details
          ref={statusFilterRef}
          className="status-filter"
          open={statusFilterOpen}
          onToggle={(event) => setStatusFilterOpen(event.currentTarget.open)}
        >
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
            <DateInput value={dateFrom} onChange={setDateFrom} ariaLabel="Дата документа с" />
          </label>
          <label>
            По
            <DateInput value={dateTo} onChange={setDateTo} ariaLabel="Дата документа по" />
          </label>
        </div>

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

        <button type="button" className="filters-reset" onClick={resetFilters}>
          Сбросить
        </button>
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
          {total !== null && items.length < total ? ` (загружаем ещё, всего ${total})…` : ""}
        </span>
        <span className="table-meta-total">Сумма: {formatAmount(filteredAmount)}</span>
        <button type="button" className="copy-button" onClick={handleCopy}>
          {copyState === "copied" ? "Скопировано ✓" : copyState === "error" ? "Не удалось скопировать" : "Скопировать"}
        </button>
      </div>

      <div className="vt-wrap" ref={scrollRef} role="table" aria-label="Заказ-наряды">
        <div className="vt-header" role="rowgroup">
          <div className="vt-row" role="row" style={{ gridTemplateColumns: GRID_TEMPLATE_COLUMNS }}>
            {COLUMNS.map((col) => (
              <div
                key={col.key}
                role="columnheader"
                className={col.numeric ? "vt-cell vt-cell--num" : "vt-cell"}
              >
                {col.label}
              </div>
            ))}
          </div>
          <div
            className="vt-row filter-row"
            role="row"
            style={{ gridTemplateColumns: GRID_TEMPLATE_COLUMNS }}
          >
            {COLUMNS.map((col) =>
              col.key === "status" ? (
                <div key={col.key} className="vt-cell" role="columnheader" />
              ) : col.key === "internal" ? (
                <div key={col.key} className="vt-cell" role="columnheader">
                  <select
                    value={internalFilter}
                    onChange={(event) => setInternalFilter(event.target.value as InternalFilter)}
                    aria-label="Фильтр по полю Внутренний"
                  >
                    <option value="all">Все</option>
                    <option value="internal">Внутр.</option>
                    <option value="external">Внешн.</option>
                  </select>
                </div>
              ) : (
                <div
                  key={col.key}
                  role="columnheader"
                  className={col.numeric ? "vt-cell vt-cell--num" : "vt-cell"}
                >
                  <input
                    type="text"
                    value={columnFilters[col.key]}
                    onChange={(event) =>
                      setColumnFilters((prev) => ({ ...prev, [col.key]: event.target.value }))
                    }
                    placeholder="Фильтр"
                    aria-label={`Фильтр по полю ${col.label}`}
                  />
                </div>
              ),
            )}
          </div>
        </div>

        {filteredRows.length === 0 ? (
          <p className="table-empty">Ничего не найдено.</p>
        ) : (
          <div
            className="vt-body"
            role="rowgroup"
            style={{ height: rowVirtualizer.getTotalSize() }}
          >
            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
              const row = filteredRows[virtualRow.index];
              return (
                <div
                  key={row.item.id}
                  data-index={virtualRow.index}
                  ref={rowVirtualizer.measureElement}
                  className="vt-row vt-row--body"
                  role="row"
                  tabIndex={0}
                  style={{
                    gridTemplateColumns: GRID_TEMPLATE_COLUMNS,
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                  onClick={() => router.push(`/work-orders/${row.item.id}`)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      router.push(`/work-orders/${row.item.id}`);
                    }
                  }}
                >
                  <div className="vt-cell" role="gridcell">
                    {row.documentDate}
                  </div>
                  <div className="vt-cell" role="gridcell">
                    {row.closedDate}
                  </div>
                  <div className="vt-cell" role="gridcell">
                    {row.number}
                  </div>
                  <div className="vt-cell" role="gridcell">
                    {row.vehicle || "—"}
                  </div>
                  <div className="vt-cell" role="gridcell">
                    {row.customer || "—"}
                  </div>
                  <div className="vt-cell" role="gridcell">
                    {row.status || "—"}
                  </div>
                  <div className="vt-cell" role="gridcell">
                    {row.internal}
                  </div>
                  <div className="vt-cell" role="gridcell">
                    {row.department || "—"}
                  </div>
                  <div className="vt-cell" role="gridcell">
                    {row.repairType || "—"}
                  </div>
                  <div className="vt-cell vt-cell--num" role="gridcell">
                    {row.amount}
                  </div>
                  <div className="vt-cell vt-cell--num" role="gridcell">
                    {row.paidAmount}
                  </div>
                  <div className="vt-cell vt-cell--num" role="gridcell">
                    {row.paymentPercent}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
