"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import { DateInput } from "@/components/DateInput";
import { AdminModal } from "@/components/settings/AdminModal";
import type { LineCallEvent, SourceSummaryResponse, SourceSummaryRow } from "@/lib/backend-api";
import { getLineCallsClient, getSourceSummaryClient } from "@/lib/telephony-client";

function pctBadgeClass(pct: number | null): string {
  if (pct === null) return "telephony-badge telephony-badge--ok";
  if (pct <= 15) return "telephony-badge telephony-badge--ok";
  if (pct <= 35) return "telephony-badge telephony-badge--warn";
  return "telephony-badge telephony-badge--down";
}

function formatPct(pct: number | null): string {
  return pct === null ? "—" : `${pct.toFixed(0)}%`;
}

function sumTotals(rows: SourceSummaryRow[]) {
  const totals = rows.reduce(
    (acc, row) => ({
      inbound_total: acc.inbound_total + row.inbound_total,
      answered: acc.answered + row.answered,
      missed: acc.missed + row.missed,
      unique_missed_callers: acc.unique_missed_callers + row.unique_missed_callers,
      outcome_called_back_reached: acc.outcome_called_back_reached + row.outcome_called_back_reached,
      outcome_called_back_not_reached: acc.outcome_called_back_not_reached + row.outcome_called_back_not_reached,
      outcome_client_called_back: acc.outcome_client_called_back + row.outcome_client_called_back,
      outcome_no_reaction: acc.outcome_no_reaction + row.outcome_no_reaction,
    }),
    {
      inbound_total: 0,
      answered: 0,
      missed: 0,
      unique_missed_callers: 0,
      outcome_called_back_reached: 0,
      outcome_called_back_not_reached: 0,
      outcome_client_called_back: 0,
      outcome_no_reaction: 0,
    },
  );
  const missedPct = totals.inbound_total ? (totals.missed / totals.inbound_total) * 100 : null;
  const reachedPct = totals.unique_missed_callers
    ? ((totals.unique_missed_callers - totals.outcome_no_reaction) / totals.unique_missed_callers) * 100
    : null;
  return { ...totals, missedPct, reachedPct };
}

function formatClient(client: string | null): string {
  if (!client) return "—";
  // "9991234567" -> "+7 999 123-45-67" - Zeon's own normalized-to-10-digits
  // shape (see backend services/zeon_client.py), always exactly 10 digits.
  if (client.length === 10) {
    return `+7 ${client.slice(0, 3)} ${client.slice(3, 6)}-${client.slice(6, 8)}-${client.slice(8, 10)}`;
  }
  return client;
}

// Same shape as formatClient above, but for a raw value that isn't
// guaranteed to be an exactly-10-digit phone (CallRecord.dst, and the
// phone half of a workshop_phone_mappings pair) - an advertising line code
// like "pan2" or "0005348" has no 10/11-digit phone shape at all and is
// returned unchanged, same as "если звонил на рекламную линию, то просто
// линию" calls for.
function formatPhoneOrLine(value: string): string {
  const digits = value.replace(/\D/g, "");
  if (digits.length === 10) {
    return `+7 ${digits.slice(0, 3)} ${digits.slice(3, 6)}-${digits.slice(6, 8)}-${digits.slice(8, 10)}`;
  }
  if (digits.length === 11 && (digits[0] === "7" || digits[0] === "8")) {
    return formatPhoneOrLine(digits.slice(1));
  }
  return value;
}

// "Куда звонили" - the line/number the client dialed (dst), with its
// paired добавочный in parens when Settings -> IP-телефония's "Цех —
// Телефон — Добавочный" table has one (dst_extension) - an advertising
// line with no specific добавочный configured, or dst with nothing in
// that table matching at all, just shows the raw line/number alone.
function calledLineCell(event: LineCallEvent): string {
  if (!event.dst) return "—";
  const base = formatPhoneOrLine(event.dst);
  return event.dst_extension ? `${base} (${event.dst_extension})` : base;
}

// "Кто ответил" - the extension that picked up, with its paired phone
// number in parens when that same mapping table has one (answered_phone) -
// an extension with no phone configured for it just shows the добавочный
// alone, same as calledLineCell's own fallback.
function answeredByCell(event: LineCallEvent): string {
  if (!event.operator) return "—";
  return event.answered_phone
    ? `${formatPhoneOrLine(event.answered_phone)} (${event.operator})`
    : event.operator;
}

function formatEventTime(time: string): string {
  // "YYYY-MM-DD HH:MM:SS" -> "ДД.ММ ЧЧ:ММ:СС"
  const [datePart, timePart] = time.split(" ");
  const [year, month, day] = datePart.split("-");
  return `${day}.${month} ${timePart}`;
}

// Every role can land on either side of "answered" - a client's own
// recall can go unanswered just as easily as the original call (they got
// missed twice in a row), and our own callback can fail to connect too.
// Label and color follow `answered`, not just the role, so a second miss
// reads as a miss instead of quietly looking like a resolved contact.
function eventLabel(event: LineCallEvent): string {
  if (event.role === "incoming") return event.answered ? "Входящий" : "Входящий (пропущен)";
  if (event.role === "callback") return event.answered ? "Наш перезвон" : "Наш перезвон (не дозвонились)";
  return event.answered ? "Клиент перезвонил" : "Клиент перезвонил (пропущен)";
}

// YandexGPT's short free-text call summary (see backend
// services/call_transcription_relay.py / models.call_record.CallRecord.
// topic_tag) - a plain label, not a quality signal (distinct from the
// ok/warn/down semantics pctBadgeClass above uses). Only ever called with a
// non-null tag - see the `event.topic_tag &&` guard at the call site, which
// renders nothing at all until the call has been summarized.
const TOPIC_UNDETERMINED = "Тема не определена";

function topicBadgeClass(tag: string): string {
  if (tag === TOPIC_UNDETERMINED) return "telephony-topic-badge telephony-topic-badge--unknown";
  return "telephony-topic-badge telephony-topic-badge--summary";
}

// YandexGPT's QA rating (see TelephonySettings.assess_quality_enabled) -
// banded the same way as the written methodology (9-10 / 7-8 / 4-6 / 1-3).
function scoreBadgeClass(score: number): string {
  if (score >= 9) return "telephony-badge telephony-badge--ok";
  if (score >= 7) return "telephony-badge telephony-badge--ok";
  if (score >= 4) return "telephony-badge telephony-badge--warn";
  return "telephony-badge telephony-badge--down";
}

function eventRowClass(event: LineCallEvent): string {
  if (!event.answered) return "telephony-event-row telephony-event-row--missed";
  if (event.role !== "incoming") return "telephony-event-row telephony-event-row--callback";
  return "telephony-event-row";
}

type EventSortKey = "time" | "client";

/** Sorting by "Номер" groups every event for the same number together, but
 * always keeps them chronological *within* a number (regardless of sort
 * direction) - the point of that sort is reading one number's whole
 * history in call order, not reversing it too. */
function sortEvents(events: LineCallEvent[], sortKey: EventSortKey, sortDir: "asc" | "desc"): LineCallEvent[] {
  const dir = sortDir === "asc" ? 1 : -1;
  return [...events].sort((a, b) => {
    if (sortKey === "client") {
      const byClient = (a.client ?? "").localeCompare(b.client ?? "") * dir;
      if (byClient !== 0) return byClient;
      return a.time.localeCompare(b.time);
    }
    return a.time.localeCompare(b.time) * dir;
  });
}

function LineCallsPanel({
  lineCode,
  startDate,
  endDate,
}: {
  lineCode: string;
  startDate: string;
  endDate: string;
}) {
  const [state, setState] = useState<"loading" | "error" | "ready">("loading");
  const [events, setEvents] = useState<LineCallEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<EventSortKey>("time");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  // Full transcript, opened explicitly by clicking a call's own topic
  // cell - a hover-only tooltip wasn't discoverable enough (per product
  // feedback, 2026-10-02: "как в интерфейсе посмотреть весь текст
  // расшифровки... ты куда-то вывел это?"). Shown whenever a transcript
  // exists at all, even before it's been classified into a topic tag (or
  // when classification is switched off entirely).
  const [transcriptEvent, setTranscriptEvent] = useState<LineCallEvent | null>(null);

  const toggleSort = (key: EventSortKey) => {
    if (key === sortKey) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    getLineCallsClient({ lineCode, startDate, endDate })
      .then((result) => {
        if (cancelled) return;
        setEvents(result.events);
        setState("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Не удалось загрузить звонки");
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [lineCode, startDate, endDate]);

  if (state === "loading") return <p className="telephony-events-status">Загрузка…</p>;
  if (state === "error") return <p className="admin-form-error">{error}</p>;
  if (events.length === 0) return <p className="telephony-events-status">Звонков не найдено</p>;

  const sorted = sortEvents(events, sortKey, sortDir);
  const sortArrow = (key: EventSortKey) => (key === sortKey ? (sortDir === "asc" ? " ▲" : " ▼") : "");

  return (
    <>
      <table className="data-table telephony-events-table">
        <thead>
          <tr>
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
            <th>Куда звонили</th>
            <th>Кто ответил</th>
            <th>Цех</th>
            <th className="telephony-num">Ожидание</th>
            <th className="telephony-num">Разговор</th>
            <th>Тема</th>
            <th>Оценка</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((event, index) => (
            <tr key={`${event.time}-${index}`} className={eventRowClass(event)}>
              <td>{formatEventTime(event.time)}</td>
              <td>{eventLabel(event)}</td>
              <td>{formatClient(event.client)}</td>
              <td>{calledLineCell(event)}</td>
              <td>{answeredByCell(event)}</td>
              <td>{event.workshop_label ?? "—"}</td>
              <td className="telephony-num">{event.wait_sec} с</td>
              <td className="telephony-num">{event.answered ? `${event.talk_sec} с` : "—"}</td>
              <td>
                {event.transcript_text ? (
                  <button
                    type="button"
                    className="telephony-topic-cell-btn"
                    onClick={() => setTranscriptEvent(event)}
                    title="Показать расшифровку"
                  >
                    {event.topic_tag ? (
                      <span className={topicBadgeClass(event.topic_tag)}>{event.topic_tag}</span>
                    ) : (
                      <span className="telephony-topic-badge telephony-topic-badge--unknown">
                        Расшифровка
                      </span>
                    )}
                  </button>
                ) : (
                  event.topic_tag && (
                    <span className={topicBadgeClass(event.topic_tag)}>{event.topic_tag}</span>
                  )
                )}
              </td>
              <td>
                {event.quality_score !== null ? (
                  <button
                    type="button"
                    className="telephony-topic-cell-btn"
                    onClick={() => setTranscriptEvent(event)}
                    title="Показать разбор звонка"
                  >
                    <span className={scoreBadgeClass(event.quality_score)}>{event.quality_score}/10</span>
                  </button>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <AdminModal
        open={transcriptEvent !== null}
        title={
          transcriptEvent
            ? `Расшифровка · ${formatClient(transcriptEvent.client)} · ${formatEventTime(transcriptEvent.time)}`
            : "Расшифровка"
        }
        onClose={() => setTranscriptEvent(null)}
        closeOnBackdropClick
        wide
      >
        {transcriptEvent?.topic_tag && (
          <p className="settings-description">
            Тема:{" "}
            <span className={topicBadgeClass(transcriptEvent.topic_tag)}>
              {transcriptEvent.topic_tag}
            </span>
          </p>
        )}
        {transcriptEvent?.quality_score !== null && transcriptEvent?.quality_score !== undefined && (
          <div className="settings-description">
            <p>
              Оценка:{" "}
              <span className={scoreBadgeClass(transcriptEvent.quality_score)}>
                {transcriptEvent.quality_score}/10
              </span>
            </p>
            {transcriptEvent.quality_review && <p>{transcriptEvent.quality_review}</p>}
          </div>
        )}
        <p className="telephony-transcript-text">{transcriptEvent?.transcript_text}</p>
        {transcriptEvent?.transcript_text_raw &&
          transcriptEvent.transcript_text_raw !== transcriptEvent.transcript_text && (
            <details className="telephony-transcript-raw">
              <summary>Исходная расшифровка (до обработки YandexGPT)</summary>
              <p className="telephony-transcript-text">{transcriptEvent.transcript_text_raw}</p>
            </details>
          )}
      </AdminModal>
    </>
  );
}

export function TelephonyStatsView({ initialSummary }: { initialSummary: SourceSummaryResponse }) {
  const [summary, setSummary] = useState(initialSummary);
  const [startDate, setStartDate] = useState(initialSummary.start_date);
  const [endDate, setEndDate] = useState(initialSummary.end_date);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedLine, setExpandedLine] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    setExpandedLine(null);
    try {
      const result = await getSourceSummaryClient({ startDate, endDate });
      setSummary(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить данные");
    } finally {
      setLoading(false);
    }
  };

  const totals = useMemo(() => sumTotals(summary.rows), [summary.rows]);

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
        <button type="button" className="admin-btn admin-btn-primary telephony-filter-btn" onClick={load} disabled={loading}>
          {loading ? "Загрузка…" : "Показать"}
        </button>
      </div>

      {error && <p className="admin-form-error">{error}</p>}

      <h2 className="chart-title">
        Итог по каждому источнику: {summary.start_date} — {summary.end_date}
      </h2>

      <table className="data-table telephony-summary-table">
        <thead>
          <tr>
            <th>Источник</th>
            <th className="telephony-num">Входящих</th>
            <th className="telephony-num">Отвечено</th>
            <th className="telephony-num">Пропущено</th>
            <th className="telephony-num">% пропуска</th>
            <th className="telephony-num">Перезвонили, дозвонились</th>
            <th className="telephony-num">Перезвонили, не дозвонились</th>
            <th className="telephony-num">Клиент перезвонил сам</th>
            <th className="telephony-num">Без реакции</th>
            <th className="telephony-num">% перезвона</th>
          </tr>
        </thead>
        <tbody>
          {summary.rows.map((row) => {
            const isExpanded = expandedLine === row.line_code;
            return (
              <Fragment key={row.line_code}>
                <tr
                  className={isExpanded ? "telephony-source-row telephony-source-row--open" : "telephony-source-row"}
                  onClick={() => setExpandedLine(isExpanded ? null : row.line_code)}
                >
                  <td>
                    <span className="telephony-expand-icon">{isExpanded ? "▾" : "▸"}</span>
                    <span className="telephony-source-name">{row.name}</span>
                    {row.caption && <span className="telephony-source-caption">{row.caption}</span>}
                  </td>
                  <td className="telephony-num">{row.inbound_total}</td>
                  <td className="telephony-num">{row.answered}</td>
                  <td className="telephony-num">{row.missed}</td>
                  <td className="telephony-num">
                    <span className={pctBadgeClass(row.missed_pct)}>{formatPct(row.missed_pct)}</span>
                  </td>
                  <td className="telephony-num">{row.outcome_called_back_reached}</td>
                  <td className="telephony-num">{row.outcome_called_back_not_reached}</td>
                  <td className="telephony-num">{row.outcome_client_called_back}</td>
                  <td className="telephony-num">{row.outcome_no_reaction}</td>
                  <td className="telephony-num">{formatPct(row.reached_pct)}</td>
                </tr>
                {isExpanded && (
                  <tr className="telephony-events-row">
                    <td colSpan={10}>
                      <LineCallsPanel lineCode={row.line_code} startDate={summary.start_date} endDate={summary.end_date} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
          {summary.rows.length === 0 && (
            <tr>
              <td colSpan={10} className="admin-empty-row">
                Звонков за выбранный период нет
              </td>
            </tr>
          )}
          {summary.rows.length > 0 && (
            <tr className="telephony-totals-row">
              <td>Все источники</td>
              <td className="telephony-num">{totals.inbound_total}</td>
              <td className="telephony-num">{totals.answered}</td>
              <td className="telephony-num">{totals.missed}</td>
              <td className="telephony-num">
                <span className={pctBadgeClass(totals.missedPct)}>{formatPct(totals.missedPct)}</span>
              </td>
              <td className="telephony-num">{totals.outcome_called_back_reached}</td>
              <td className="telephony-num">{totals.outcome_called_back_not_reached}</td>
              <td className="telephony-num">{totals.outcome_client_called_back}</td>
              <td className="telephony-num">{totals.outcome_no_reaction}</td>
              <td className="telephony-num">{formatPct(totals.reachedPct)}</td>
            </tr>
          )}
        </tbody>
      </table>

      <p className="settings-description">
        Таблица показывает только входящие звонки — у исходящих нет своей линии/источника в Zeon,
        поэтому число импортированных звонков за период будет больше суммы «Входящих» здесь (в него
        входят и наши исходящие). «% пропуска» — доля входящих звонков на источник, оставшихся без
        ответа. «% перезвона» — доля уникальных пропустивших клиентов, с которыми в итоге связались
        (мы перезвонили и дозвонились, либо клиент перезвонил сам и ему ответили) в течение 24 часов
        с момента пропуска. Нажмите на строку источника, чтобы увидеть список звонков по времени.
      </p>
    </div>
  );
}
