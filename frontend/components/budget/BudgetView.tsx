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

type MetricKey = "plan_revenue" | "fact_revenue" | "expenses" | "profit" | "payments" | "money";
type EditableKey = "plan_revenue" | "expenses";

const METRICS: { key: MetricKey; label: string; editable: boolean }[] = [
  { key: "plan_revenue", label: "Выручка план", editable: true },
  { key: "fact_revenue", label: "Выручка факт", editable: false },
  { key: "expenses", label: "Расходы", editable: true },
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
  const fact = Number(month.fact_revenue);
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

function EditableCell({ value, onCommit }: { value: string; onCommit: (next: string) => void }) {
  const [draft, setDraft] = useState(value);
  const [focused, setFocused] = useState(false);
  useEffect(() => setDraft(value), [value]);

  return (
    <input
      type="text"
      inputMode="decimal"
      className="budget-cell-input"
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

export function BudgetView({ initialData }: { initialData: BudgetYear }) {
  const currentYear = new Date().getFullYear();
  const currentMonth = new Date().getMonth() + 1;

  const [year, setYear] = useState(initialData.year);
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isFirstRender = useRef(true);
  const currentMonthHeaderRef = useRef<HTMLTableCellElement | null>(null);
  const hasScrolledToToday = useRef(false);

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

  useEffect(() => {
    if (hasScrolledToToday.current || year !== currentYear) return;
    currentMonthHeaderRef.current?.scrollIntoView({ inline: "center", block: "nearest" });
    hasScrolledToToday.current = true;
  }, [year, currentYear]);

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

      <div className="budget-scroll">
        <table className="budget-table">
          <thead>
            <tr>
              <th className="budget-th-workshop">Цех</th>
              <th className="budget-th-metric">Показатель</th>
              {MONTH_LABELS.map((label, idx) => {
                const isCurrent = year === currentYear && idx + 1 === currentMonth;
                return (
                  <th
                    key={label}
                    ref={isCurrent ? currentMonthHeaderRef : undefined}
                    className={isCurrent ? "budget-th-month budget-th-month--current" : "budget-th-month"}
                  >
                    {label}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {data.workshops.map((ws) =>
              METRICS.map((metric, metricIdx) => (
                <tr key={`${ws.workshop_id}-${metric.key}`}>
                  {metricIdx === 0 && (
                    <td className="budget-td-workshop" rowSpan={METRICS.length}>
                      {ws.workshop_label}
                    </td>
                  )}
                  <td className="budget-td-metric">{metric.label}</td>
                  {ws.months.map((m) => {
                    const isCurrent = year === currentYear && m.month === currentMonth;
                    const value = m[metric.key];
                    const negative =
                      (metric.key === "profit" || metric.key === "money") && Number(value) < 0;
                    const classes = [
                      "budget-td-month",
                      isCurrent && "budget-td-month--current",
                      negative && "budget-td-month--negative",
                    ]
                      .filter(Boolean)
                      .join(" ");
                    return (
                      <td key={m.month} className={classes}>
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
                  })}
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
