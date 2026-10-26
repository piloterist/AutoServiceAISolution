"use client";

import { useEffect, useRef, useState } from "react";

import type { BudgetMonthValues, BudgetYear } from "@/lib/backend-api";

const MONTH_LABELS = [
  "Янв",
  "Фев",
  "Мар",
  "Апр",
  "Май",
  "Июн",
  "Июл",
  "Авг",
  "Сен",
  "Окт",
  "Ноя",
  "Дек",
];

type MetricKey =
  | "plan_revenue"
  | "fact_revenue_insurance"
  | "fact_revenue_main"
  | "expenses"
  | "profit"
  | "payments"
  | "money";
type EditableKey = "plan_revenue";

const METRICS: { key: MetricKey; label: string; editable: boolean }[] = [
  { key: "plan_revenue", label: "Выручка план", editable: true },
  { key: "fact_revenue_insurance", label: "Выручка факт страховые", editable: false },
  { key: "fact_revenue_main", label: "Выручка факт основные", editable: false },
  // Not typed in here any more: the sum of the cost items on Финансы -> Расходы.
  { key: "expenses", label: "Расходы", editable: false },
  { key: "profit", label: "Прибыль", editable: false },
  { key: "payments", label: "Оплаты", editable: false },
  { key: "money", label: "Деньги", editable: false },
];

function formatRub(value: string): string {
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return n.toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}

// Профиль/Деньги depend only on fields already on the client (fact_revenue/
// payments from the server, expenses from this edit) - recomputed locally
// so an edit updates the whole row instantly, no round-trip needed just to
// see the derived numbers change.
function recompute(month: BudgetMonthValues): BudgetMonthValues {
  const fact = Number(month.fact_revenue_insurance) + Number(month.fact_revenue_main);
  const expenses = Number(month.expenses);
  const payments = Number(month.payments);
  return { ...month, profit: String(fact - expenses), money: String(payments - expenses) };
}

// Grouped with spaces while not focused (per product feedback, 2026-10-03:
// a plain "5000000" wasn't readable) - plain digits while editing, since a
// native text input can't keep the caret position sane while reformatting
// on every keystroke.
function formatDraftForDisplay(raw: string): string {
  const n = Number(raw);
  if (raw.trim() === "" || Number.isNaN(n)) return raw;
  return n.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

export function EditableCell({
  value,
  onCommit,
  disabled = false,
}: {
  value: string;
  onCommit: (next: string) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  const [focused, setFocused] = useState(false);
  useEffect(() => setDraft(value), [value]);

  return (
    <input
      type="text"
      inputMode="decimal"
      className="budget-cell-input"
      disabled={disabled}
      value={focused ? draft : formatDraftForDisplay(draft)}
      onFocus={() => setFocused(true)}
      onChange={(event) => setDraft(event.target.value.replace(/[^\d.]/g, ""))}
      onBlur={() => {
        setFocused(false);
        const next = draft.trim() === "" ? "0" : draft;
        if (Number(next) !== Number(value)) {
          onCommit(next);
        } else {
          setDraft(value);
        }
      }}
    />
  );
}

/** Бюджеты (product ask, 2026-10-26: laid out like Расходы): the metrics down,
 * the months across with the workshops side by side inside each month, large
 * cells, the item names pinned on the left, a scrollbar above and below, and
 * the current month first on screen. */
export function BudgetView({ initialData }: { initialData: BudgetYear }) {
  const currentYear = new Date().getFullYear();
  const currentMonth = new Date().getMonth() + 1;

  const [year, setYear] = useState(initialData.year);
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isFirstRender = useRef(true);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const topScrollRef = useRef<HTMLDivElement | null>(null);
  const currentMonthHeaderRef = useRef<HTMLTableCellElement | null>(null);
  const syncing = useRef(false);
  const [tableWidth, setTableWidth] = useState(0);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`/api/budget?year=${year}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<BudgetYear>;
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
  }, [year]);

  // The current month is the first one on screen, right after the pinned
  // "Показатель" column; another year starts at January. Runs when the shown
  // year changes, not on every edit.
  const shownYear = data.year;
  useEffect(() => {
    const box = scrollRef.current;
    if (!box) return;
    const target = shownYear === currentYear ? currentMonthHeaderRef.current : null;
    const firstColumn = box.querySelector<HTMLElement>(".expenses-th-item");
    box.scrollLeft = target ? target.offsetLeft - (firstColumn?.offsetWidth ?? 0) : 0;
  }, [shownYear, currentYear]);

  // A second scrollbar above the table, kept in step with the bottom one.
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

  const handleCommit = (workshopId: string, month: number, field: EditableKey, value: string) => {
    setData((prev) => ({
      ...prev,
      workshops: prev.workshops.map((ws) =>
        ws.workshop_id !== workshopId
          ? ws
          : {
              ...ws,
              months: ws.months.map((m) =>
                m.month !== month ? m : recompute({ ...m, [field]: value }),
              ),
            },
      ),
    }));

    fetch("/api/budget", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workshop_id: workshopId, year, month, field, value: Number(value) }),
    }).catch(() => setError("Не удалось сохранить значение"));
  };

  const cellClass = (month: number, workshopIndex: number, extra = "") =>
    [
      "budget-td-month",
      year === currentYear && month === currentMonth ? "budget-td-month--current" : "",
      month % 2 === 0 ? "expenses-month-even" : "expenses-month-odd",
      workshopIndex === 0 ? "expenses-month-start" : "",
      extra,
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
      </div>

      {error && <p className="admin-form-error">{error}</p>}

      <div className="expenses-scroll-top" ref={topScrollRef} onScroll={() => syncScroll("top")} aria-hidden="true">
        <div style={{ width: tableWidth, height: 1 }} />
      </div>
      <div className="budget-scroll" ref={scrollRef} onScroll={() => syncScroll("bottom")}>
        <table className="budget-table expenses-table">
          <thead>
            <tr>
              <th className="expenses-th-item" rowSpan={2}>
                Показатель
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
            {METRICS.map((metric) => (
              <tr key={metric.key}>
                <td className="expenses-td-item">{metric.label}</td>
                {MONTH_LABELS.flatMap((label, monthIdx) =>
                  data.workshops.map((ws, wsIdx) => {
                    const m = ws.months[monthIdx];
                    const value = m[metric.key];
                    const negative =
                      (metric.key === "profit" || metric.key === "money") && Number(value) < 0;
                    return (
                      <td
                        key={`${label}-${ws.workshop_id}`}
                        className={cellClass(monthIdx + 1, wsIdx, negative ? "budget-td-month--negative" : "")}
                      >
                        {metric.editable ? (
                          <EditableCell
                            value={value}
                            onCommit={(next) =>
                              handleCommit(ws.workshop_id, m.month, metric.key as EditableKey, next)
                            }
                          />
                        ) : (
                          formatRub(value)
                        )}
                      </td>
                    );
                  }),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
