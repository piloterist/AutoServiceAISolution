"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import type { BudgetMonthValues, BudgetYear } from "@/lib/backend-api";
import type { BudgetRevenueKind } from "@/lib/budget-revenue";

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

const MONTH_NAMES = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
];

type MetricKey =
  | "plan_revenue"
  | "fact_revenue"
  | "fact_revenue_insurance"
  | "fact_revenue_insurance_labor"
  | "fact_revenue_insurance_parts"
  | "fact_revenue_main"
  | "fact_revenue_main_labor"
  | "fact_revenue_main_parts"
  | "expenses"
  | "profit"
  | "cash_profit"
  | "revenue_paid"
  | "revenue_unpaid"
  | "revenue_overdue"
  | "revenue_not_due"
  | "payments"
  | "money";
type EditableKey = "plan_revenue";

// `level`: 1 = a sub-row of the row above it (shown indented, in a lighter style) -
// the fact revenue rows are made up of their Работы and Запчасти.
const METRICS: { key: MetricKey; label: string; editable: boolean; level?: 1 | 2; parent?: boolean; hidden?: boolean }[] = [
  { key: "plan_revenue", label: "Выручка план", editable: true },
  { key: "fact_revenue", label: "Выручка общая", editable: false, parent: true },
  { key: "fact_revenue_insurance", label: "Выручка факт страховые", editable: false, parent: true },
  { key: "fact_revenue_insurance_labor", label: "Работы", editable: false, level: 1 },
  { key: "fact_revenue_insurance_parts", label: "Запчасти", editable: false, level: 1 },
  { key: "fact_revenue_main", label: "Выручка факт основные", editable: false, parent: true },
  { key: "fact_revenue_main_labor", label: "Работы", editable: false, level: 1 },
  { key: "fact_revenue_main_parts", label: "Запчасти", editable: false, level: 1 },
  // Not typed in here any more: the sum of the cost items on Финансы -> Расходы.
  { key: "expenses", label: "Расходы", editable: false },
  { key: "profit", label: "Чистая прибыль", editable: false },
  { key: "revenue_paid", label: "Оплачено", editable: false },
  { key: "revenue_unpaid", label: "Без оплат", editable: false, parent: true },
  { key: "revenue_overdue", label: "Просрочено", editable: false, level: 1 },
  { key: "revenue_not_due", label: "Ожидание", editable: false, level: 1 },
  { key: "cash_profit", label: "Денежная прибыль", editable: false },
  { key: "payments", label: "Приход денег", editable: false },
  // Скрыта по просьбе (2026-11-26): расчёт остаётся, строка не показывается.
  { key: "money", label: "Деньги", editable: false, hidden: true },
];

const HIDDEN_WORKSHOPS_KEY = "budget-hidden-workshops";

// Короткие пояснения «как считается» - по клику на «?» справа от названия строки.
const METRIC_HINTS: Record<MetricKey, string> = {
  plan_revenue: "Плановая выручка, вводится вручную.",
  fact_revenue: "Страховые + основные: заказ-наряды, закрытые в периоде.",
  fact_revenue_insurance: "Сумма заказ-нарядов страховых, закрытых в периоде.",
  fact_revenue_insurance_labor: "Работы в страховых заказ-нарядах.",
  fact_revenue_insurance_parts: "Запчасти в страховых заказ-нарядах.",
  fact_revenue_main: "Сумма заказ-нарядов «Текущий», закрытых в периоде.",
  fact_revenue_main_labor: "Работы в основных заказ-нарядах.",
  fact_revenue_main_parts: "Запчасти в основных заказ-нарядах.",
  expenses: "Сумма статей на листе Финансы → Расходы.",
  profit: "Выручка общая − Расходы.",
  cash_profit: "Чистая прибыль − Без оплат.",
  revenue_paid: "Сколько из выручки периода уже оплачено.",
  revenue_unpaid: "Остаток долга по заказ-нарядам выручки, оплаченным не полностью.",
  revenue_overdue: "Часть «Без оплат», по которой истёк срок: физлица - день после закрытия, юрлица - 21 день от счёта (нет счёта - от закрытия).",
  revenue_not_due: "Часть «Без оплат», по которой срок ещё не истёк.",
  payments: "Все поступления денег в периоде по любым заказ-нарядам (в т.ч. закрытым раньше).",
  money: "Приход денег − Расходы.",
};

// Строки, значения которых ведут на лист «Заказ наряды» с готовым фильтром (клик по ячейке).
const DRILL_KIND: Partial<Record<MetricKey, BudgetRevenueKind>> = {
  fact_revenue: "all",
  revenue_unpaid: "unpaid",
  revenue_overdue: "overdue",
  revenue_not_due: "not_due",
  fact_revenue_insurance: "insurance",
  fact_revenue_main: "main",
};

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
  return {
    ...month,
    profit: String(fact - expenses),
    cash_profit: String(fact - expenses - Number(month.revenue_unpaid)),
    money: String(payments - expenses),
  };
}

// Сумма значений показателя по набору месяцев (по цехам одного месяца - "Вся компания",
// по месяцам периода - столбец ИТОГО). Все показатели аддитивны: прибыль и деньги тоже
// складываются (сумма разностей = разность сумм).
function sumMetric(months: BudgetMonthValues[], key: MetricKey): string {
  return String(months.reduce((sum, m) => sum + Number(m[key]), 0));
}

type YearMonth = { year: number; month: number };

const YEAR_OPTIONS_BACK = 4;

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
 * cells, the item names pinned on the left, one scrollbar below (the table has
 * few rows), a "Вся компания" column closing each month and the previous month
 * first on screen.
 *
 * Период (product ask, 2026-11-25): the months shown are chosen "с месяц год по месяц год"
 * (may span several years - each year is fetched once and kept), and an ИТОГО group closes
 * the table: the same workshops and "Вся компания", every row summed over the chosen period. */
export function BudgetView({ initialData }: { initialData: BudgetYear }) {
  const currentYear = new Date().getFullYear();
  const currentMonth = new Date().getMonth() + 1;

  const [from, setFrom] = useState<YearMonth>({ year: initialData.year, month: 1 });
  const [to, setTo] = useState<YearMonth>({ year: initialData.year, month: 12 });
  const [dataByYear, setDataByYear] = useState<Record<number, BudgetYear>>({
    [initialData.year]: initialData,
  });
  const [loading, setLoading] = useState(false);
  const [hintKey, setHintKey] = useState<MetricKey | null>(null);
  const [hiddenWorkshops, setHiddenWorkshops] = useState<string[]>([]);
  const [wsMenuOpen, setWsMenuOpen] = useState(false);
  const wsMenuRef = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(HIDDEN_WORKSHOPS_KEY);
      if (saved) setHiddenWorkshops(JSON.parse(saved) as string[]);
    } catch {
      /* нет сохранённого выбора */
    }
  }, []);
  useEffect(() => {
    if (!wsMenuOpen) return;
    const close = (e: MouseEvent) => {
      if (wsMenuRef.current && !wsMenuRef.current.contains(e.target as Node)) setWsMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [wsMenuOpen]);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const previousMonthHeaderRef = useRef<HTMLTableCellElement | null>(null);

  // Months of the chosen period, oldest first.
  const cols: YearMonth[] = [];
  for (let y = from.year; y <= to.year; y++) {
    const first = y === from.year ? from.month : 1;
    const last = y === to.year ? to.month : 12;
    for (let m = first; m <= last; m++) cols.push({ year: y, month: m });
  }
  const years = Array.from(new Set(cols.map((c) => c.year)));
  const multiYear = years.length > 1;
  const missingYears = years.filter((y) => !dataByYear[y]);
  const ready = missingYears.length === 0;
  const rangeKey = `${from.year}-${from.month}:${to.year}-${to.month}`;

  useEffect(() => {
    if (missingYears.length === 0) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all(
      missingYears.map((y) =>
        fetch(`/api/budget?year=${y}`).then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json() as Promise<BudgetYear>;
        }),
      ),
    )
      .then((fresh) => {
        if (cancelled) return;
        setDataByYear((prev) => {
          const next = { ...prev };
          fresh.forEach((d, i) => {
            next[missingYears[i]] = d;
          });
          return next;
        });
      })
      .catch(() => {
        if (!cancelled) setError("Не удалось загрузить данные за выбранный период");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [missingYears.join(",")]);

  // The month BEFORE the current one is the first on screen, right after the pinned
  // "Показатель" column (so the closed month is in view) when it is in the period; otherwise
  // the first month. Runs when the period changes, not on every edit.
  useEffect(() => {
    const box = scrollRef.current;
    if (!box || !ready) return;
    const target = previousMonthHeaderRef.current;
    const firstColumn = box.querySelector<HTMLElement>(".expenses-th-item");
    box.scrollLeft = target ? target.offsetLeft - (firstColumn?.offsetWidth ?? 0) : 0;
  }, [rangeKey, ready]);

  const allWorkshops = (dataByYear[years[0]] ?? initialData).workshops;
  // Подразделения, снятые галкой в фильтре; хранятся «скрытые», чтобы новые цеха показывались сами.
  const workshops = allWorkshops.filter((w) => !hiddenWorkshops.includes(w.workshop_id));
  const toggleWorkshop = (id: string) => {
    const next = hiddenWorkshops.includes(id)
      ? hiddenWorkshops.filter((x) => x !== id)
      : [...hiddenWorkshops, id];
    if (allWorkshops.every((w) => next.includes(w.workshop_id))) return; // хотя бы один остаётся
    setHiddenWorkshops(next);
    try {
      window.localStorage.setItem(HIDDEN_WORKSHOPS_KEY, JSON.stringify(next));
    } catch {
      /* storage недоступен - выбор живёт до перезагрузки */
    }
  };
  const monthOf = (workshopId: string, col: YearMonth): BudgetMonthValues | undefined =>
    dataByYear[col.year]?.workshops.find((w) => w.workshop_id === workshopId)?.months[col.month - 1];

  const handleCommit = (workshopId: string, year: number, month: number, field: EditableKey, value: string) => {
    setDataByYear((prev) => {
      const current = prev[year];
      if (!current) return prev;
      return {
        ...prev,
        [year]: {
          ...current,
          workshops: current.workshops.map((ws) =>
            ws.workshop_id !== workshopId
              ? ws
              : {
                  ...ws,
                  months: ws.months.map((m) =>
                    m.month !== month ? m : recompute({ ...m, [field]: value }),
                  ),
                },
          ),
        },
      };
    });

    fetch("/api/budget", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workshop_id: workshopId, year, month, field, value: Number(value) }),
    }).catch(() => setError("Не удалось сохранить значение"));
  };

  // Keeps from <= to: moving one edge past the other drags the other along.
  const setFromChecked = (next: YearMonth) => {
    setFrom(next);
    if (next.year * 12 + next.month > to.year * 12 + to.month) setTo(next);
  };
  const setToChecked = (next: YearMonth) => {
    setTo(next);
    if (next.year * 12 + next.month < from.year * 12 + from.month) setFrom(next);
  };
  const shiftYears = (delta: number) => {
    setFrom((f) => ({ ...f, year: f.year + delta }));
    setTo((t) => ({ ...t, year: t.year + delta }));
  };
  const isCurrentYearWhole =
    from.year === currentYear && from.month === 1 && to.year === currentYear && to.month === 12;

  const yearOptions = Array.from({ length: YEAR_OPTIONS_BACK + 2 }, (_, i) => currentYear - YEAR_OPTIONS_BACK + i);
  for (const y of [from.year, to.year]) if (!yearOptions.includes(y)) yearOptions.push(y);
  yearOptions.sort((a, b) => a - b);

  const periodSelect = (label: string, value: YearMonth, onChange: (v: YearMonth) => void) => (
    <span className="budget-period">
      <span className="budget-period-label">{label}</span>
      <select
        className="budget-select"
        aria-label={`${label}: месяц`}
        value={value.month}
        onChange={(e) => onChange({ ...value, month: Number(e.target.value) })}
      >
        {MONTH_NAMES.map((name, i) => (
          <option key={name} value={i + 1}>
            {name}
          </option>
        ))}
      </select>
      <select
        className="budget-select"
        aria-label={`${label}: год`}
        value={value.year}
        onChange={(e) => onChange({ ...value, year: Number(e.target.value) })}
      >
        {yearOptions.map((y) => (
          <option key={y} value={y}>
            {y}
          </option>
        ))}
      </select>
    </span>
  );

  const monthParity = (idx: number) => ((idx + 1) % 2 === 0 ? "expenses-month-even" : "expenses-month-odd");

  const cellClass = (col: YearMonth, idx: number, workshopIndex: number, extra = "") =>
    [
      "budget-td-month",
      col.year === currentYear && col.month === currentMonth ? "budget-td-month--current" : "",
      monthParity(idx),
      workshopIndex === 0 ? "expenses-month-start" : "",
      extra,
    ]
      .filter(Boolean)
      .join(" ");

  // Значение ячейки; у строк «Выручка факт страховые/основные» - ссылка на лист ЗН, где уже стоит
  // фильтр: ровно те заказ-наряды, из которых сложилась сумма (отбор делает сервер теми же
  // условиями, что и сумма). Цех - workshop_id, «Вся компания» - без него. Закрыт в этом месяце
  // (closed_from/closed_to) заодно не даёт странице подставить запомненные фильтры.
  const renderValue = (
    key: MetricKey,
    value: string,
    year: number,
    month: number,
    workshopId: string | null,
    end?: YearMonth, // последний месяц периода (столбец ИТОГО); без него - один месяц
  ) => {
    const kind = DRILL_KIND[key];
    if (!kind || Number(value) === 0) return formatRub(value);
    const mm = String(month).padStart(2, "0");
    const last = end ?? { year, month };
    const lastDay = new Date(last.year, last.month, 0).getDate();
    const params = new URLSearchParams({
      budget_revenue: kind,
      budget_year: String(year),
      budget_month: String(month),
      closed_from: `${year}-${mm}-01`,
      closed_to: `${last.year}-${String(last.month).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`,
    });
    if (end) {
      params.set("budget_year_to", String(end.year));
      params.set("budget_month_to", String(end.month));
    }
    if (workshopId) params.set("workshop_id", workshopId);
    // «Вся компания» при скрытых подразделениях - только по видимым цехам, как и сумма.
    else if (hiddenWorkshops.length > 0) {
      params.set("workshop_ids", workshops.map((w) => w.workshop_id).join(","));
    }
    return (
      <Link href={`/work-orders?${params.toString()}`} className="budget-drill" title="Показать заказ-наряды">
        {formatRub(value)}
      </Link>
    );
  };

  const prevMonthCol: YearMonth =
    currentMonth > 1 ? { year: currentYear, month: currentMonth - 1 } : { year: currentYear, month: 1 };
  const colLabel = (col: YearMonth) =>
    multiYear ? `${MONTH_LABELS[col.month - 1]} ${col.year}` : MONTH_LABELS[col.month - 1];

  // ИТОГО: per workshop (summed over the period's months) and the whole company.
  const periodMonthsOf = (workshopId: string): BudgetMonthValues[] =>
    cols.map((c) => monthOf(workshopId, c)).filter((m): m is BudgetMonthValues => m !== undefined);
  const allMonths = workshops.flatMap((ws) => periodMonthsOf(ws.workshop_id));
  const totalIdx = cols.length;

  return (
    <div className="card budget-card">
      <div className="budget-toolbar">
        <button type="button" className="admin-btn" onClick={() => shiftYears(-1)} aria-label="Сдвинуть период на год назад">
          ←
        </button>
        {periodSelect("С", from, setFromChecked)}
        {periodSelect("По", to, setToChecked)}
        <button type="button" className="admin-btn" onClick={() => shiftYears(1)} aria-label="Сдвинуть период на год вперёд">
          →
        </button>
        <button
          type="button"
          className="admin-btn"
          disabled={isCurrentYearWhole}
          onClick={() => {
            setFrom({ year: currentYear, month: 1 });
            setTo({ year: currentYear, month: 12 });
          }}
        >
          Текущий год
        </button>
        <span className="budget-ws-filter" ref={wsMenuRef}>
          <button
            type="button"
            className="budget-select budget-ws-btn"
            aria-expanded={wsMenuOpen}
            onClick={() => setWsMenuOpen((o) => !o)}
          >
            Подразделения: {workshops.length === allWorkshops.length ? "все" : `${workshops.length} из ${allWorkshops.length}`}
          </button>
          {wsMenuOpen && (
            <div className="budget-ws-menu">
              {allWorkshops.map((ws) => (
                <label key={ws.workshop_id} className="budget-ws-item">
                  <input
                    type="checkbox"
                    checked={!hiddenWorkshops.includes(ws.workshop_id)}
                    onChange={() => toggleWorkshop(ws.workshop_id)}
                  />
                  {ws.workshop_label}
                </label>
              ))}
            </div>
          )}
        </span>
        {loading && <span className="admin-hint">Загрузка…</span>}
      </div>

      {error && <p className="admin-form-error">{error}</p>}

      {ready && (
        <div className="budget-scroll" ref={scrollRef}>
          <table className="budget-table expenses-table">
            <thead>
              <tr>
                <th className="expenses-th-item" rowSpan={2}>
                  Показатель
                </th>
                {cols.map((col, idx) => {
                  const isCurrent = col.year === currentYear && col.month === currentMonth;
                  const isScrollTarget = col.year === prevMonthCol.year && col.month === prevMonthCol.month;
                  return (
                    <th
                      key={`${col.year}-${col.month}`}
                      colSpan={workshops.length + 1}
                      ref={isScrollTarget ? previousMonthHeaderRef : undefined}
                      className={[
                        "budget-th-month expenses-th-month expenses-month-start",
                        isCurrent ? "budget-th-month--current" : "",
                        monthParity(idx),
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      {colLabel(col)}
                    </th>
                  );
                })}
                <th
                  colSpan={workshops.length + 1}
                  className={["budget-th-month expenses-th-month expenses-month-start budget-th-total", monthParity(totalIdx)].join(" ")}
                >
                  ИТОГО
                  <span className="budget-total-range">
                    {" "}
                    {MONTH_LABELS[from.month - 1]} {from.year} – {MONTH_LABELS[to.month - 1]} {to.year}
                  </span>
                </th>
              </tr>
              <tr>
                {[...cols, null].flatMap((col, colIdx) => {
                  const keyBase = col ? `${col.year}-${col.month}` : "total";
                  return [
                    ...workshops.map((ws, wsIdx) => (
                      <th
                        key={`${keyBase}-${ws.workshop_id}`}
                        className={[
                          "expenses-th-workshop",
                          wsIdx === 0 ? "expenses-month-start" : "",
                          monthParity(colIdx),
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        title={ws.workshop_label}
                      >
                        {ws.workshop_label.replace(" — ", "\n")}
                      </th>
                    )),
                    <th
                      key={`${keyBase}-company`}
                      className={["expenses-th-workshop budget-th-company", monthParity(colIdx)].join(" ")}
                    >
                      Вся компания
                    </th>,
                  ];
                })}
              </tr>
            </thead>
            <tbody>
              {METRICS.filter((metric) => !metric.hidden).map((metric) => (
                <tr key={metric.key} className={metric.level ? "budget-row--sub" : metric.parent ? "budget-row--parent" : undefined}>
                  <td className={hintKey === metric.key ? "expenses-td-item budget-td--hint" : "expenses-td-item"}>
                    {metric.level ? `└ ${metric.label}` : metric.label}
                    <button
                      type="button"
                      className="budget-hint-btn"
                      aria-label={`Как считается «${metric.label}»`}
                      aria-expanded={hintKey === metric.key}
                      onClick={() => setHintKey(hintKey === metric.key ? null : metric.key)}
                    >
                      ?
                    </button>
                    {hintKey === metric.key && <div className="budget-hint">{METRIC_HINTS[metric.key]}</div>}
                  </td>
                  {cols.flatMap((col, colIdx) => {
                    const keyBase = `${col.year}-${col.month}`;
                    const cells = workshops.map((ws, wsIdx) => {
                      const m = monthOf(ws.workshop_id, col);
                      const value = m ? m[metric.key] : "0";
                      const negative =
                        (metric.key === "profit" || metric.key === "cash_profit" || metric.key === "money") &&
                        Number(value) < 0;
                      return (
                        <td
                          key={`${keyBase}-${ws.workshop_id}`}
                          className={cellClass(col, colIdx, wsIdx, negative ? "budget-td-month--negative" : "")}
                        >
                          {metric.editable ? (
                            <EditableCell
                              value={value}
                              onCommit={(next) =>
                                handleCommit(ws.workshop_id, col.year, col.month, metric.key as EditableKey, next)
                              }
                            />
                          ) : (
                            renderValue(metric.key, value, col.year, col.month, ws.workshop_id)
                          )}
                        </td>
                      );
                    });
                    const companyValue = sumMetric(
                      workshops
                        .map((ws) => monthOf(ws.workshop_id, col))
                        .filter((m): m is BudgetMonthValues => m !== undefined),
                      metric.key,
                    );
                    const negative =
                      (metric.key === "profit" || metric.key === "cash_profit" || metric.key === "money") &&
                      Number(companyValue) < 0;
                    return [
                      ...cells,
                      <td
                        key={`${keyBase}-company`}
                        className={cellClass(
                          col,
                          colIdx,
                          1,
                          ["budget-td-company", negative ? "budget-td-month--negative" : ""].join(" "),
                        )}
                      >
                        {renderValue(metric.key, companyValue, col.year, col.month, null)}
                      </td>,
                    ];
                  })}
                  {[
                    ...workshops.map((ws, wsIdx) => {
                      const value = sumMetric(periodMonthsOf(ws.workshop_id), metric.key);
                      const negative =
                        (metric.key === "profit" || metric.key === "cash_profit" || metric.key === "money") &&
                        Number(value) < 0;
                      return (
                        <td
                          key={`total-${ws.workshop_id}`}
                          className={[
                            "budget-td-month budget-td-total",
                            monthParity(totalIdx),
                            wsIdx === 0 ? "expenses-month-start" : "",
                            negative ? "budget-td-month--negative" : "",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                        >
                          {renderValue(metric.key, value, from.year, from.month, ws.workshop_id, to)}
                        </td>
                      );
                    }),
                    (() => {
                      const value = sumMetric(allMonths, metric.key);
                      const negative =
                        (metric.key === "profit" || metric.key === "cash_profit" || metric.key === "money") &&
                        Number(value) < 0;
                      return (
                        <td
                          key="total-company"
                          className={[
                            "budget-td-month budget-td-total budget-td-company",
                            monthParity(totalIdx),
                            negative ? "budget-td-month--negative" : "",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                        >
                          {renderValue(metric.key, value, from.year, from.month, null, to)}
                        </td>
                      );
                    })(),
                  ]}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
