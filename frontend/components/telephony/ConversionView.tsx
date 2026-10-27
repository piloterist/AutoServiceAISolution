"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import { DateInput } from "@/components/DateInput";
import { CallRecordingPlayer } from "@/components/telephony/CallRecordingPlayer";
import {
  CallEventsTable,
  TOPIC_UNDETERMINED,
  TopicCell,
  TranscriptModal,
  answeredByCell,
  calledLineCell,
  eventLabel,
  eventRowClass,
  formatClient,
  formatEventTime,
} from "@/components/telephony/TelephonyStatsView";
import type { ConversionGroup, LineCallEvent } from "@/lib/backend-api";
import { COHORTS, groupInCohort, parseCohort, type Cohort } from "@/lib/conversion-cohorts";
import { getConversionClient } from "@/lib/telephony-client";

// "Конверсия" can list a few thousand rows for a long period - render it in
// pages instead of putting hundreds of recording players on the page at once.
const PAGE_SIZE = 200;
const COLUMN_COUNT = 16;
// A call counts as a real conversation from this many seconds of talk time
// (same threshold as the backend's MIN_REAL_TALK_SEC).
const REAL_TALK_SEC = 5;

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** First and last day of the current month, "YYYY-MM-DD" - the page's
 * default period (product ask, 2026-10-23: "по умолчанию текущий месяц"). */
function currentMonthRange(): { start: string; end: string } {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  const lastDay = new Date(year, month + 1, 0).getDate();
  return {
    start: `${year}-${pad(month + 1)}-01`,
    end: `${year}-${pad(month + 1)}-${pad(lastDay)}`,
  };
}

type YesNo = "" | "yes" | "no";
// "Определена" = YandexGPT gave the call a real topic; "Нет" = no topic at all
// or "Тема не определена".
type TopicFilter = "" | "defined" | "none";

type Filters = {
  source: string;
  time: string;
  event: string;
  number: string;
  callsCount: string;
  dst: string;
  operator: string;
  workshop: string;
  wait: string;
  talk: string;
  topic: TopicFilter;
  hasRequest: YesNo;
  hasWorkOrder: YesNo;
  existing: YesNo;
};

type TextFilterKey = "time" | "number" | "callsCount" | "dst" | "operator" | "wait" | "talk";
type SelectFilterKey = "source" | "event" | "workshop";
type YesNoFilterKey = "hasRequest" | "hasWorkOrder" | "existing";

const EMPTY_FILTERS: Filters = {
  source: "",
  time: "",
  event: "",
  number: "",
  callsCount: "",
  dst: "",
  operator: "",
  workshop: "",
  wait: "",
  talk: "",
  topic: "",
  hasRequest: "",
  hasWorkOrder: "",
  existing: "",
};

// How a missing source/цех is shown in the table and offered as a filter value.
const NO_VALUE = "—";

function groupKey(group: ConversionGroup): string {
  return `${group.client}|${group.work_order_id ?? ""}|${group.request_id ?? ""}`;
}

function includesText(haystack: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  return !q || haystack.toLowerCase().includes(q);
}

/** A numeric filter (Звонков, Ожидание, Разговор): ">30", "<5", ">=10",
 * "<=60", "=7" compare the number; several can be combined for a range
 * (">30 <60"); a plain number ("30") means exactly that; anything else is
 * matched as text against the displayed value ("12 с"). */
function matchesNumeric(value: number | null, displayed: string, query: string): boolean {
  const q = query.trim();
  if (!q) return true;

  if (/^\d+$/.test(q)) return value === Number(q);

  const conditionPattern = /(>=|<=|>|<|=)\s*(\d+)/g;
  const conditions = Array.from(q.matchAll(conditionPattern));
  const onlyConditions = q.replace(conditionPattern, "").trim() === "";
  if (conditions.length > 0 && onlyConditions) {
    if (value === null) return false;
    return conditions.every(([, operator, limitText]) => {
      const limit = Number(limitText);
      switch (operator) {
        case ">":
          return value > limit;
        case "<":
          return value < limit;
        case ">=":
          return value >= limit;
        case "<=":
          return value <= limit;
        default:
          return value === limit;
      }
    });
  }
  return displayed.toLowerCase().includes(q.toLowerCase());
}

function matchesNumberText(event: LineCallEvent, query: string): boolean {
  const q = query.trim();
  if (!q) return true;
  const digits = q.replace(/\D/g, "");
  if (digits && (event.client ?? "").includes(digits)) return true;
  return formatClient(event.client).toLowerCase().includes(q.toLowerCase());
}

function matchesYesNo(value: boolean, filter: YesNo): boolean {
  if (!filter) return true;
  return filter === "yes" ? value : !value;
}

/** The per-call filters (everything except the group-level ones). */
function callMatches(event: LineCallEvent, f: Filters): boolean {
  if (f.source && (event.source_name ?? NO_VALUE) !== f.source) return false;
  if (!includesText(formatEventTime(event.time), f.time)) return false;
  if (f.event && eventLabel(event) !== f.event) return false;
  if (!matchesNumberText(event, f.number)) return false;
  if (!includesText(calledLineCell(event), f.dst)) return false;
  if (!includesText(answeredByCell(event), f.operator)) return false;
  if (f.workshop && (event.workshop_label ?? NO_VALUE) !== f.workshop) return false;
  if (!matchesNumeric(event.wait_sec, `${event.wait_sec} с`, f.wait)) return false;
  const talkShown = event.answered ? `${event.talk_sec} с` : NO_VALUE;
  if (!matchesNumeric(event.answered ? event.talk_sec : null, talkShown, f.talk)) return false;
  const hasTopic = Boolean(event.topic_tag) && event.topic_tag !== TOPIC_UNDETERMINED;
  if (f.topic === "defined" && !hasTopic) return false;
  if (f.topic === "none" && hasTopic) return false;
  return true;
}

type Row = {
  key: string;
  group: ConversionGroup;
  // The call the row shows: the group's first call WITH A CONVERSATION that
  // passes the per-call filters, else its first call that passes them.
  call: LineCallEvent;
};

function sortedUnique(values: string[]): string[] {
  return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b, "ru"));
}

function formatShortDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

type SortKey = "time" | "client";

/** Телефония -> "Конверсия": the inbound calls of a period, one row per
 * phone number and work order they led to (several calls of one number
 * collapse into one row - click it to see them all); a number with several
 * work orders in the period gets one row per work order. */
export function ConversionView({
  initialStart,
  initialEnd,
  initialCohort,
  initialDepartments,
  includeRequests = false,
}: {
  // From the Аналитика donuts' links (/telephony?tab=conversion&from=&to=&cohort=):
  // that page's period, and which numbers to show. Default: the current
  // month, everyone.
  initialStart?: string;
  initialEnd?: string;
  initialCohort?: string;
  // Comma-separated raw 1C department names - the dashboard's department
  // filter, so the tab shows the same workshop(s) as the donuts.
  initialDepartments?: string;
  // "Включить заявки на ремонт": a repair request after a call counts as a conversion.
  includeRequests?: boolean;
}) {
  const initial = useMemo(() => {
    const month = currentMonthRange();
    return { start: initialStart || month.start, end: initialEnd || month.end };
  }, [initialStart, initialEnd]);
  const [startDate, setStartDate] = useState(initial.start);
  const [endDate, setEndDate] = useState(initial.end);
  const [cohort, setCohort] = useState<Cohort>(() => parseCohort(initialCohort));
  const [departments, setDepartments] = useState<string[]>(() =>
    (initialDepartments ?? "")
      .split(",")
      .map((name) => name.trim())
      .filter(Boolean),
  );
  const [groups, setGroups] = useState<ConversionGroup[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [sortKey, setSortKey] = useState<SortKey>("time");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [transcriptEvent, setTranscriptEvent] = useState<LineCallEvent | null>(null);

  const load = useCallback(async (from: string, to: string, depts: string[]) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getConversionClient({
        startDate: from,
        endDate: to,
        departments: depts,
        includeRequests,
      });
      setGroups(result.groups);
      setExpanded(new Set());
      setVisibleCount(PAGE_SIZE);
    } catch (err) {
      setGroups(null);
      setError(err instanceof Error ? err.message : "Не удалось загрузить звонки");
    } finally {
      setLoading(false);
    }
  }, [includeRequests]);

  useEffect(() => {
    void load(initial.start, initial.end, departments);
    // Loads once on mount; later changes go through the buttons below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, initial]);

  const setFilter = <K extends keyof Filters>(key: K, value: Filters[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setVisibleCount(PAGE_SIZE);
  };

  const rows: Row[] = useMemo(() => {
    if (!groups) return [];
    const result: Row[] = [];
    for (const group of groups) {
      if (!groupInCohort(group, cohort)) continue;
      if (!matchesYesNo(group.is_existing, filters.existing)) continue;
      if (!matchesYesNo(Boolean(group.request_id), filters.hasRequest)) continue;
      if (!matchesYesNo(Boolean(group.work_order_id), filters.hasWorkOrder)) continue;
      if (!matchesNumeric(group.calls.length, String(group.calls.length), filters.callsCount)) continue;
      const matching = group.calls.filter((c) => callMatches(c, filters));
      if (matching.length === 0) continue;
      // The row shows the first call that had a real conversation (a missed
      // call followed by our answered callback shows the callback), else
      // simply the first call.
      const call = matching.find((c) => c.answered && c.talk_sec >= REAL_TALK_SEC) ?? matching[0];
      result.push({ key: groupKey(group), group, call });
    }
    return result;
  }, [groups, filters, cohort]);

  const sortedRows = useMemo(() => {
    const dir = sortDir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      if (sortKey === "client") {
        const byClient = a.group.client.localeCompare(b.group.client) * dir;
        if (byClient !== 0) return byClient;
      }
      return a.group.calls[0].time.localeCompare(b.group.calls[0].time) * (sortKey === "time" ? dir : 1);
    });
  }, [rows, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "time" ? "desc" : "asc");
    }
  };
  const sortArrow = (key: SortKey) => (key === sortKey ? (sortDir === "asc" ? " ▲" : " ▼") : "");

  const toggleExpanded = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const options = useMemo(() => {
    const calls = (groups ?? []).flatMap((g) => g.calls);
    return {
      source: sortedUnique(calls.map((e) => e.source_name ?? NO_VALUE)),
      event: sortedUnique(calls.map(eventLabel)),
      workshop: sortedUnique(calls.map((e) => e.workshop_label ?? NO_VALUE)),
    };
  }, [groups]);

  // Statistics count phone numbers, not calls (product ask, 2026-10-23):
  // every number once, however many calls or work orders it has. A number is
  // "existing" if it already was one at its first call of the (filtered) list.
  const stats = useMemo(() => {
    if (!groups) return null;
    const phones = new Set<string>();
    const converted = new Set<string>();
    const workOrders = new Set<string>();
    const firstGroupByPhone = new Map<string, ConversionGroup>();
    for (const { group } of rows) {
      phones.add(group.client);
      // A repair request converts the number like a work order does.
      if (group.work_order_id || group.request_id) converted.add(group.client);
      if (group.work_order_id) workOrders.add(group.work_order_id);
      const earliest = firstGroupByPhone.get(group.client);
      if (!earliest || group.calls[0].time < earliest.calls[0].time) {
        firstGroupByPhone.set(group.client, group);
      }
    }
    const existing = Array.from(firstGroupByPhone.values()).filter((g) => g.is_existing).length;
    const allPhones = new Set(groups.map((g) => g.client)).size;
    return {
      phones: phones.size,
      allPhones,
      converted: converted.size,
      workOrders: workOrders.size,
      existing,
    };
  }, [groups, rows]);

  const filtersActive = Object.values(filters).some((value) => value !== "");

  const textInput = (key: TextFilterKey, label: string, placeholder = "Фильтр") => (
    <input
      type="search"
      className="telephony-col-filter"
      value={filters[key]}
      onChange={(e) => setFilter(key, e.target.value)}
      aria-label={`Фильтр: ${label}`}
      placeholder={placeholder}
    />
  );

  const selectInput = (key: SelectFilterKey, label: string, values: string[]) => (
    <select
      className="telephony-col-filter"
      value={filters[key]}
      onChange={(e) => setFilter(key, e.target.value)}
      aria-label={`Фильтр: ${label}`}
    >
      <option value="">Все</option>
      {values.map((value) => (
        <option key={value} value={value}>
          {value}
        </option>
      ))}
    </select>
  );

  const yesNoInput = (key: YesNoFilterKey, label: string) => (
    <select
      className="telephony-col-filter"
      value={filters[key]}
      onChange={(e) => setFilter(key, e.target.value as YesNo)}
      aria-label={`Фильтр: ${label}`}
    >
      <option value="">Все</option>
      <option value="yes">Да</option>
      <option value="no">Нет</option>
    </select>
  );

  const shown = sortedRows.slice(0, visibleCount);

  return (
    <div className="card">
      <div className="telephony-filter-bar">
        <label className="telephony-filter-label">
          С
          <DateInput value={startDate} onChange={setStartDate} ariaLabel="Период с" className="telephony-date-input" />
        </label>
        <label className="telephony-filter-label">
          По
          <DateInput value={endDate} onChange={setEndDate} ariaLabel="Период по" className="telephony-date-input" />
        </label>
        <button
          type="button"
          className="admin-btn admin-btn-primary telephony-filter-btn"
          onClick={() => void load(startDate, endDate, departments)}
          disabled={loading || !startDate || !endDate}
        >
          {loading ? "Загрузка…" : "Показать"}
        </button>
        {departments.length > 0 && (
          <span className="phone-filter-chip">
            Цех: {departments.join(", ")}
            <button
              type="button"
              className="phone-filter-chip-clear"
              onClick={() => {
                setDepartments([]);
                void load(startDate, endDate, []);
              }}
              aria-label="Снять фильтр по цеху"
            >
              ×
            </button>
          </span>
        )}
        <label className="telephony-filter-label">
          Выборка
          <select
            className="telephony-date-input telephony-cohort-select"
            value={cohort}
            onChange={(event) => {
              setCohort(event.target.value as Cohort);
              setVisibleCount(PAGE_SIZE);
            }}
            aria-label="Выборка номеров"
          >
            {COHORTS.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="admin-btn telephony-filter-btn telephony-filters-reset"
          onClick={() => {
            setFilters(EMPTY_FILTERS);
            setCohort("all");
            setVisibleCount(PAGE_SIZE);
          }}
          disabled={!filtersActive && cohort === "all"}
        >
          Сбросить фильтры
        </button>
      </div>

      {error && <p className="admin-form-error">{error}</p>}

      {stats && (
        <p className="telephony-conversion-stats">
          Уникальных номеров: <strong>{stats.phones}</strong>
          {stats.phones !== stats.allPhones && <> из {stats.allPhones}</>} · с заказ-нарядом:{" "}
          <strong>{stats.converted}</strong> · заказ-нарядов: <strong>{stats.workOrders}</strong> · существующих
          клиентов: <strong>{stats.existing}</strong>
        </p>
      )}

      {groups && groups.length === 0 && <p className="telephony-events-status">Звонков за период нет</p>}
      {groups && groups.length > 0 && (
        <>
          <table className="data-table telephony-events-table telephony-conversion-table">
            <thead>
              <tr>
                <th>Источник</th>
                <th>
                  <button type="button" className="telephony-sort-btn" onClick={() => toggleSort("time")}>
                    Время{sortArrow("time")}
                  </button>
                </th>
                <th>Событие</th>
                <th>
                  <button type="button" className="telephony-sort-btn" onClick={() => toggleSort("client")}>
                    Номер{sortArrow("client")}
                  </button>
                </th>
                <th className="telephony-num">Звонков</th>
                <th>Куда звонили</th>
                <th>Кто ответил</th>
                <th>Цех</th>
                <th className="telephony-num">Ожидание</th>
                <th className="telephony-num">Разговор</th>
                <th>Тема</th>
                <th>Запись</th>
                <th>Заявка на ремонт</th>
                <th>Заказ-наряд</th>
                <th>Существующий</th>
                <th />
              </tr>
              <tr className="telephony-filter-row">
                <th>{selectInput("source", "Источник", options.source)}</th>
                <th>{textInput("time", "Время")}</th>
                <th>{selectInput("event", "Событие", options.event)}</th>
                <th>{textInput("number", "Номер")}</th>
                <th>{textInput("callsCount", "Звонков", ">1")}</th>
                <th>{textInput("dst", "Куда звонили")}</th>
                <th>{textInput("operator", "Кто ответил")}</th>
                <th>{selectInput("workshop", "Цех", options.workshop)}</th>
                <th>{textInput("wait", "Ожидание", ">30")}</th>
                <th>{textInput("talk", "Разговор", ">30")}</th>
                <th>
                  <select
                    className="telephony-col-filter"
                    value={filters.topic}
                    onChange={(e) => setFilter("topic", e.target.value as TopicFilter)}
                    aria-label="Фильтр: Тема"
                  >
                    <option value="">Все</option>
                    <option value="defined">Определена</option>
                    <option value="none">Нет</option>
                  </select>
                </th>
                <th />
                <th>{yesNoInput("hasRequest", "Заявка на ремонт")}</th>
                <th>{yesNoInput("hasWorkOrder", "Заказ-наряд")}</th>
                <th>{yesNoInput("existing", "Существующий")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.map(({ key, group, call }) => {
                const isOpen = expanded.has(key);
                const total = group.calls.length;
                return (
                  <Fragment key={key}>
                    <tr
                      className={
                        isOpen
                          ? `${eventRowClass(call)} telephony-group-row telephony-group-row--open`
                          : `${eventRowClass(call)} telephony-group-row`
                      }
                      aria-expanded={isOpen}
                      onClick={(event) => {
                        // A click on the row opens/closes its calls; clicks on
                        // the controls inside it (links, player, topic) do not.
                        if ((event.target as HTMLElement).closest("a, button, audio, select, input")) return;
                        toggleExpanded(key);
                      }}
                    >
                      <td>{call.source_name ?? "—"}</td>
                      <td>{formatEventTime(call.time)}</td>
                      <td>{eventLabel(call)}</td>
                      <td>{formatClient(call.client)}</td>
                      <td className="telephony-num">
                        {total}
                      </td>
                      <td>{calledLineCell(call)}</td>
                      <td>{answeredByCell(call)}</td>
                      <td>{call.workshop_label ?? "—"}</td>
                      <td className="telephony-num">{call.wait_sec} с</td>
                      <td className="telephony-num">{call.answered ? `${call.talk_sec} с` : "—"}</td>
                      <td>
                        <TopicCell event={call} onOpenTranscript={setTranscriptEvent} />
                      </td>
                      <td>
                        <CallRecordingPlayer callId={call.call_id} hasRecording={call.has_recording} />
                      </td>
                      <td>
                        {group.request_id ? (
                          <>
                            <Link href={`/work-orders/${group.request_id}`} className="telephony-wo-link">
                              {group.request_number}
                            </Link>
                            <div className="telephony-wo-date">от {formatShortDate(group.request_created_date)}</div>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        {group.work_order_id ? (
                          <>
                            <Link href={`/work-orders/${group.work_order_id}`} className="telephony-wo-link">
                              {group.work_order_number}
                            </Link>
                            <div className="telephony-wo-date">от {formatShortDate(group.work_order_created_date)}</div>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        {group.is_existing ? (
                          <span className="telephony-badge telephony-badge--ok">Да</span>
                        ) : (
                          "Нет"
                        )}
                      </td>
                      <td>
                        <Link
                          href={`/work-orders?phone=${group.client}`}
                          target="_blank"
                          rel="noopener"
                          className="admin-btn telephony-open-wo-btn"
                        >
                          Открыть ЗН
                        </Link>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="telephony-events-row">
                        <td colSpan={COLUMN_COUNT}>
                          <CallEventsTable events={group.calls} showSource />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>

          {sortedRows.length === 0 && (
            <p className="telephony-events-status">Нет звонков, подходящих под фильтры</p>
          )}
          {sortedRows.length > shown.length && (
            <button
              type="button"
              className="admin-btn telephony-more-btn"
              onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
            >
              Показать ещё (осталось {sortedRows.length - shown.length})
            </button>
          )}
        </>
      )}

      <TranscriptModal event={transcriptEvent} onClose={() => setTranscriptEvent(null)} />

      <p className="settings-description">
        Одна строка — один номер и один заказ-наряд, к которому привели его звонки: все звонки номера до создания
        заказ-наряда (по дате создания в 1С) собраны в одну строку, нажмите на неё, чтобы увидеть каждый звонок с
        расшифровкой и записью. Если у номера за период было несколько заказ-нарядов, будет несколько строк;
        звонки после последнего заказ-наряда — отдельная строка без заказ-наряда. В группу входят и наши перезвоны на
        пропущенные; в строке показан первый звонок, по которому состоялся разговор (иначе — первый звонок). «Существующий: Да» — на номер уже был хотя бы один заказ-наряд (любой статус) до первого звонка
        строки. Статистика считает уникальные номера. Звонки сотрудников не учитываются. В полях «Звонков»,
        «Ожидание» и «Разговор» можно вводить условия со знаками &gt; &lt; &gt;= &lt;= = (например «&gt;30» или
        диапазон «&gt;30 &lt;60»), число без знака — точное значение. Тема «Нет» — тема пустая или «Тема не
        определена».
      </p>
    </div>
  );
}
