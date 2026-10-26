"use client";

import { useEffect, useRef, useState } from "react";

import type { ExpensesYear } from "@/lib/backend-api";

import { EditableCell } from "./BudgetView";
import { ExpensesImportDialog } from "./ExpensesImportDialog";

const MONTH_LABELS = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];

function formatRub(value: string): string {
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return n.toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}

/** Финансы -> Расходы (product ask, 2026-10-26): per workshop, the cost
 * items (Настройки -> Финансы) by the months of a chosen year, same shape and
 * year switch as Бюджеты. A cell can be typed in only for an ACTIVE item
 * (an inactive one is locked); the month's total per workshop is what the
 * Бюджеты "Расходы" row shows. */
export function ExpensesView() {
  const currentYear = new Date().getFullYear();
  const currentMonth = new Date().getMonth() + 1;

  const [year, setYear] = useState(currentYear);
  // The P&L report is for a closed month: offer the previous one by default.
  const previousMonth =
    currentMonth === 1 ? { year: currentYear - 1, month: 12 } : { year: currentYear, month: currentMonth - 1 };
  const [data, setData] = useState<ExpensesYear | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const topScrollRef = useRef<HTMLDivElement | null>(null);
  const syncing = useRef(false);
  const [tableWidth, setTableWidth] = useState(0);
  const [importOpen, setImportOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const currentMonthHeaderRef = useRef<HTMLTableCellElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`/api/expenses?year=${year}`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<ExpensesYear>;
      })
      .then((fresh) => {
        if (!cancelled) setData(fresh);
      })
      .catch(() => {
        if (!cancelled) setError("Не удалось загрузить данные за этот год");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [year, reloadKey]);

  // The current month is always the first one on screen (right after the
  // sticky "Статья затрат" column); another year starts at January. Runs when
  // the year changes / the first data arrives, not on every edit.
  const loadedYear = data?.year ?? null;
  useEffect(() => {
    const box = scrollRef.current;
    if (!box || loadedYear === null) return;
    const target = loadedYear === currentYear ? currentMonthHeaderRef.current : null;
    const firstColumn = box.querySelector<HTMLElement>(".expenses-th-item");
    box.scrollLeft = target
      ? target.offsetLeft - (firstColumn?.offsetWidth ?? 0)
      : 0;
  }, [loadedYear, currentYear]);

  // A second scrollbar ABOVE the table, kept in step with the one below it
  // (product ask, 2026-10-26): the table is wide, and the bottom one is far away.
  useEffect(() => {
    const box = scrollRef.current;
    if (!box) return;
    const measure = () => setTableWidth(box.scrollWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    const table = box.querySelector("table");
    if (table) observer.observe(table);
    return () => observer.disconnect();
  }, [data]);

  const syncScroll = (from: "top" | "bottom") => {
    if (syncing.current) {
      syncing.current = false;
      return;
    }
    const source = from === "top" ? topScrollRef.current : scrollRef.current;
    const target = from === "top" ? scrollRef.current : topScrollRef.current;
    if (!source || !target || target.scrollLeft === source.scrollLeft) return;
    syncing.current = true;
    target.scrollLeft = source.scrollLeft;
  };

  const commit = (workshopId: string, itemId: string, month: number, value: string) => {
    fetch("/api/expenses", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cost_item_id: itemId,
        workshop_id: workshopId,
        year,
        month,
        amount: String(Number(value) || 0),
      }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(typeof body.error === "string" ? body.error : "Не удалось сохранить значение");
        }
        // Re-read: totals and locked state come from the server.
        const fresh = await fetch(`/api/expenses?year=${year}`, { cache: "no-store" });
        if (fresh.ok) setData((await fresh.json()) as ExpensesYear);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Не удалось сохранить значение"));
  };

  const items = data?.items ?? [];

  // A month's block starts with a thicker left border; the current month is tinted.
  const cellClass = (month: number, workshopIndex: number) =>
    [
      "budget-td-month",
      year === currentYear && month === currentMonth ? "budget-td-month--current" : "",
      month % 2 === 0 ? "expenses-month-even" : "expenses-month-odd",
      workshopIndex === 0 ? "expenses-month-start" : "",
    ]
      .filter(Boolean)
      .join(" ");

  return (
    <div className="card budget-card">
      <div className="budget-toolbar">
        <button type="button" className="admin-btn" onClick={() => setYear((y) => y - 1)} aria-label="Предыдущий год">
          ←
        </button>
        <span className="budget-year">{year}</span>
        <button type="button" className="admin-btn" onClick={() => setYear((y) => y + 1)} aria-label="Следующий год">
          →
        </button>
        <button
          type="button"
          className="admin-btn"
          disabled={year === currentYear}
          onClick={() => setYear(currentYear)}
        >
          Текущий
        </button>
        {loading && <span className="admin-hint">Загрузка…</span>}
        <span className="admin-form-actions-spacer" />
        <button type="button" className="admin-btn" onClick={() => setImportOpen(true)}>
          Импорт
        </button>
      </div>

      {error && <p className="admin-form-error">{error}</p>}

      {importOpen && (
        <ExpensesImportDialog
          defaultYear={previousMonth.year}
          defaultMonth={previousMonth.month}
          onClose={() => setImportOpen(false)}
          onImported={(importedYear) => {
            setYear(importedYear);
            setReloadKey((k) => k + 1);
          }}
        />
      )}

      {data && items.length === 0 && (
        <p className="admin-hint">
          Статей затрат пока нет — добавьте их в Настройки → Финансы.
        </p>
      )}

      {data && items.length > 0 && (
        <>
        <div
          className="expenses-scroll-top"
          ref={topScrollRef}
          onScroll={() => syncScroll("top")}
          aria-hidden="true"
        >
          <div style={{ width: tableWidth, height: 1 }} />
        </div>
        <div className="budget-scroll" ref={scrollRef} onScroll={() => syncScroll("bottom")}>
          <table className="budget-table expenses-table">
            <thead>
              <tr>
                <th className="expenses-th-item" rowSpan={2}>
                  Статья затрат
                </th>
                {MONTH_LABELS.map((label, idx) => {
                  const isCurrent = year === currentYear && idx + 1 === currentMonth;
                  return (
                    <th
                      key={label}
                      colSpan={data.workshops.length}
                      ref={isCurrent ? currentMonthHeaderRef : undefined}
                      className={[
                        "budget-th-month expenses-th-month expenses-month-start",
                        isCurrent ? "budget-th-month--current" : "",
                        (idx + 1) % 2 === 0 ? "expenses-month-even" : "expenses-month-odd",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      {label}
                    </th>
                  );
                })}
              </tr>
              <tr>
                {MONTH_LABELS.flatMap((label, monthIdx) =>
                  data.workshops.map((ws, wsIdx) => (
                    <th
                      key={`${label}-${ws.workshop_id}`}
                      className={[
                        "expenses-th-workshop",
                        wsIdx === 0 ? "expenses-month-start" : "",
                        (monthIdx + 1) % 2 === 0 ? "expenses-month-even" : "expenses-month-odd",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      title={ws.workshop_label}
                    >
                      {ws.workshop_label.replace(" — ", "\n")}
                    </th>
                  )),
                )}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td className="expenses-td-item">
                    {item.name}
                    {!item.is_active && <span className="expenses-inactive"> (неактивна)</span>}
                  </td>
                  {MONTH_LABELS.flatMap((label, monthIdx) =>
                    data.workshops.map((ws, wsIdx) => {
                      const row = ws.rows.find((r) => r.cost_item_id === item.id);
                      return (
                        <td key={`${label}-${ws.workshop_id}`} className={cellClass(monthIdx + 1, wsIdx)}>
                          <EditableCell
                            value={row?.months[monthIdx] ?? "0"}
                            disabled={!item.is_active}
                            onCommit={(next) => commit(ws.workshop_id, item.id, monthIdx + 1, next)}
                          />
                        </td>
                      );
                    }),
                  )}
                </tr>
              ))}
              <tr className="expenses-total-row">
                <td className="expenses-td-item">Итого</td>
                {MONTH_LABELS.flatMap((label, monthIdx) =>
                  data.workshops.map((ws, wsIdx) => (
                    <td key={`${label}-${ws.workshop_id}`} className={cellClass(monthIdx + 1, wsIdx)}>
                      {formatRub(ws.totals[monthIdx])}
                    </td>
                  )),
                )}
              </tr>
            </tbody>
          </table>
        </div>
        </>
      )}
    </div>
  );
}
