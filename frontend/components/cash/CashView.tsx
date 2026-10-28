"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { CashCalendar } from "@/components/cash/CashCalendar";
import { CashEntryDialog, KIND_LABELS } from "@/components/cash/CashEntryDialog";
import { DateInput } from "@/components/DateInput";
import type {
  CashBook,
  CashContext,
  CashEntry,
  CashKind,
  CashScope,
  CashSearchHit,
} from "@/lib/backend-api";
import { getCashBookClient, searchCashEntriesClient } from "@/lib/cash-client";
import { formatDay, formatMoney, todayMsk } from "@/lib/money";

const COLUMNS: { kind: CashKind; title: string }[] = [
  { kind: "cash_in", title: KIND_LABELS.cash_in },
  { kind: "card_in", title: KIND_LABELS.card_in },
  { kind: "cash_out", title: KIND_LABELS.cash_out },
];

type DialogState = { entry: CashEntry | null; kind: CashKind } | null;

function money(value: string): string {
  return `${formatMoney(value)} ₽`;
}

/** Касса (product ask, 2026-10-24): the cash book of a workshop. Department /
 * workshop tabs on top (only the desks the user may see - the server decides),
 * a calendar with a С/По period beside it, the opening balance, three big
 * buttons, the closing balance, and below them three columns (Приход НАЛ,
 * Приход КАРТА, Расход НАЛ) with the entries and their totals. Clicking an
 * entry opens the same dialog used to create one. */
export function CashView({ context }: { context: CashContext }) {
  const today = useMemo(todayMsk, []);
  const [workshopId, setWorkshopId] = useState<string | null>(context.default_workshop_id);
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(today);
  // The С/По fields are a draft: the book only changes when "Показать" is
  // pressed. Picking a day in the calendar resets both at once.
  const [draftFrom, setDraftFrom] = useState(today);
  const [draftTo, setDraftTo] = useState(today);
  const [book, setBook] = useState<CashBook | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<DialogState>(null);
  // "Касса" filter (whole book / cash only / personal cards only) and, below the
  // period, one employee's personal card ("" = none). A chosen employee shows that
  // card, whatever the filter says.
  const [scope, setScope] = useState<CashScope>("all");
  const [cardHolderId, setCardHolderId] = useState("");
  const cardHolder = context.card_holders.find((h) => h.id === cardHolderId) ?? null;
  const [lock, setLock] = useState({ from: context.lock_from, to: context.lock_to });
  // Search by work-order number: every hit of the desk, earliest first; the
  // arrows walk through them, the page jumps to the hit's day.
  const [searchText, setSearchText] = useState("");
  const [hits, setHits] = useState<CashSearchHit[]>([]);
  const [hitIndex, setHitIndex] = useState(0);
  const [searchNote, setSearchNote] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const foundId = hits.length > 0 ? hits[hitIndex]?.id : null;

  const workshop = context.workshops.find((w) => w.id === workshopId) ?? null;
  const departments = useMemo(() => {
    const seen = new Map<string, string>();
    for (const w of context.workshops) seen.set(w.department_id, w.department_name);
    return Array.from(seen, ([id, name]) => ({ id, name }));
  }, [context.workshops]);
  const workshopTypes = context.workshops.filter((w) => w.department_id === workshop?.department_id);

  const load = useCallback(async () => {
    if (!workshopId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getCashBookClient({
        workshopId,
        dateFrom: from,
        dateTo: to,
        scope,
        cardHolderId: cardHolderId || undefined,
      });
      setBook(result);
      setLock({ from: result.lock_from, to: result.lock_to });
    } catch (err) {
      setBook(null);
      setError(err instanceof Error ? err.message : "Не удалось загрузить кассу");
    } finally {
      setLoading(false);
    }
  }, [workshopId, from, to, scope, cardHolderId]);

  useEffect(() => {
    void load();
  }, [load]);

  const goToHit = (list: CashSearchHit[], index: number) => {
    const hit = list[index];
    if (!hit) return;
    setHitIndex(index);
    setFrom(hit.entry_date);
    setTo(hit.entry_date);
    setDraftFrom(hit.entry_date);
    setDraftTo(hit.entry_date);
  };

  const runSearch = async () => {
    const text = searchText.trim();
    if (!workshopId || !text) return;
    setSearching(true);
    setSearchNote(null);
    try {
      const found = await searchCashEntriesClient(workshopId, text);
      setHits(found);
      if (found.length === 0) setSearchNote("Не найдено");
      else goToHit(found, 0);
    } catch (err) {
      setHits([]);
      setSearchNote(err instanceof Error ? err.message : "Не удалось выполнить поиск");
    } finally {
      setSearching(false);
    }
  };

  // "Сбросить": drops the search and goes back to today.
  const resetSearch = () => {
    setSearchText("");
    setHits([]);
    setHitIndex(0);
    setSearchNote(null);
    selectDay(today);
  };

  // After the book of the hit's day is loaded, bring the entry into view.
  useEffect(() => {
    if (!foundId || !book) return;
    document.getElementById(`cash-entry-${foundId}`)?.scrollIntoView({ block: "nearest" });
  }, [foundId, book]);

  const selectDay = (day: string) => {
    setFrom(day);
    setTo(day);
    setDraftFrom(day);
    setDraftTo(day);
  };

  // The draft's "С" can't pass "По": moving one drags the other along.
  const changeFrom = (value: string) => {
    if (!value) return;
    setDraftFrom(value);
    if (value > draftTo) setDraftTo(value);
  };
  const changeTo = (value: string) => {
    if (!value) return;
    setDraftTo(value);
    if (value < draftFrom) setDraftFrom(value);
  };
  const applyPeriod = () => {
    setFrom(draftFrom);
    setTo(draftTo);
  };
  const periodChanged = draftFrom !== from || draftTo !== to;
  const resetFilters = () => {
    selectDay(today);
    setCardHolderId("");
    setScope("all");
  };

  const selectDepartment = (departmentId: string) => {
    const candidates = context.workshops.filter((w) => w.department_id === departmentId);
    // Keep the same kind of workshop (Кузовной/Слесарный) when the new
    // department has one - what the user is most likely after.
    const same = candidates.find((w) => w.workshop_type === workshop?.workshop_type);
    setWorkshopId((same ?? candidates[0])?.id ?? null);
    setHits([]);
    setSearchNote(null);
  };

  // A new entry goes to today when the period contains it, else to the first
  // day. Without "Корректировка кассы" only today is writable.
  const newEntryDate = from <= context.today && context.today <= to ? context.today : from;
  const canAdd = context.can_correct || newEntryDate === context.today;

  const singleDay = from === to;
  const period = singleDay ? formatDay(from) : `${formatDay(from)} — ${formatDay(to)}`;

  const entriesOf = (kind: CashKind) => book?.entries.filter((e) => e.kind === kind) ?? [];
  const totalOf = (kind: CashKind) =>
    book ? book.totals[kind] : "0";

  return (
    <div className="cash-layout">
      {/* Left column (product ask, 2026-10-24): everything that picks WHICH
          book to look at - cash desk, day, period - so the right side is all
          book, from the very top of the page. */}
      <aside className="cash-sidebar card">
        <h1 className="planner-title">Касса</h1>

        <div className="planner-dept-switch cash-dept-switch">
          {departments.map((department) => (
            <button
              key={department.id}
              type="button"
              className={
                department.id === workshop?.department_id ? "planner-dept-btn planner-dept-btn--on" : "planner-dept-btn"
              }
              onClick={() => selectDepartment(department.id)}
            >
              {department.name}
            </button>
          ))}
        </div>

        <div className="admin-tabs planner-workshop-type-tabs">
          {workshopTypes.map((w) => (
            <button
              key={w.id}
              type="button"
              className={w.id === workshopId ? "admin-tab admin-tab--on" : "admin-tab"}
              onClick={() => {
                setWorkshopId(w.id);
                setHits([]);
                setSearchNote(null);
              }}
            >
              {w.workshop_type}
            </button>
          ))}
        </div>

        <div className="cash-filter">
          <label htmlFor="cash-scope">Касса</label>
          <select
            id="cash-scope"
            className="cash-filter-select"
            value={cardHolderId ? "personal" : scope}
            disabled={Boolean(cardHolderId)}
            onChange={(event) => setScope(event.target.value as CashScope)}
          >
            <option value="all">Вся касса</option>
            <option value="cash">Наличка</option>
            <option value="personal">Личные карты</option>
          </select>
        </div>

        <div className="cash-filter">
          <label htmlFor="cash-card-holder">Личная карта</label>
          <select
            id="cash-card-holder"
            className="cash-filter-select cash-filter-select--holder"
            value={cardHolderId}
            onChange={(event) => setCardHolderId(event.target.value)}
            title="Личная карта сотрудника: движение и остаток"
          >
            <option value="">— сотрудник —</option>
            {context.card_holders.map((holder) => (
              <option key={holder.id} value={holder.id}>
                {holder.name}
              </option>
            ))}
          </select>
        </div>

        <CashCalendar
          from={from}
          to={to}
          today={today}
          lockFrom={lock.from}
          lockTo={lock.to}
          onSelectDay={selectDay}
        />

        <div className="cash-period">
          <h2 className="chart-title">Произвольный период</h2>
          <div className="cash-period-row">
            <span>С</span>
            <DateInput value={draftFrom} onChange={changeFrom} ariaLabel="Период с" className="telephony-date-input" />
          </div>
          <div className="cash-period-row">
            <span>По</span>
            <DateInput value={draftTo} onChange={changeTo} ariaLabel="Период по" className="telephony-date-input" />
          </div>
          <button
            type="button"
            className="admin-btn admin-btn-primary cash-period-apply"
            onClick={applyPeriod}
            disabled={!periodChanged}
          >
            Показать
          </button>
          {/* Back to today, no employee card, the whole book. */}
          <button type="button" className="admin-btn cash-period-apply cash-period-reset" onClick={resetFilters}>
            Сбросить
          </button>
          {/* A plain link: the file is built by the server and just opens/downloads - nothing is saved by us. */}
          {workshopId && draftFrom && draftTo && draftFrom <= draftTo ? (
            <a
              className="admin-btn cash-period-apply cash-period-excel"
              href={`/api/cash/export?workshop_id=${workshopId}&date_from=${draftFrom}&date_to=${draftTo}`}
              title="Все операции кассы за указанный период — файл Excel"
            >
              В Excel
            </a>
          ) : (
            <span className="admin-btn cash-period-apply cash-period-excel cash-period-excel--off" aria-disabled="true">
              В Excel
            </span>
          )}
          {lock.from && lock.to && (
            <p className="cash-lock-note">
              🔒 Заблокирован период {formatDay(lock.from)} — {formatDay(lock.to)}
            </p>
          )}
        </div>
      </aside>

      <div className="cash-main">
      {error && <p className="admin-form-error">{error}</p>}

      <div className="card cash-book">
        <div className="cash-book-title">
          <h2 className="chart-title">
            {workshop ? `${workshop.department_name} — ${workshop.workshop_type}` : "Касса"}
          </h2>
          <span className="cash-book-period">{period}</span>
          {loading && <span className="cash-book-loading">Загрузка…</span>}
          <div className="cash-search">
            <button
              type="button"
              className="admin-btn cash-search-arrow"
              disabled={hitIndex <= 0 || hits.length < 2}
              onClick={() => goToHit(hits, hitIndex - 1)}
              aria-label="Предыдущая запись"
            >
              ←
            </button>
            <input
              className="cash-search-input"
              value={searchText}
              placeholder="Номер ЗН или текст комментария"
              onChange={(event) => setSearchText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void runSearch();
              }}
            />
            <button
              type="button"
              className="admin-btn admin-btn-primary cash-search-go"
              disabled={searching || !searchText.trim()}
              onClick={() => void runSearch()}
            >
              Найти
            </button>
            <button type="button" className="admin-btn cash-search-reset" onClick={resetSearch}>
              Сбросить
            </button>
            <button
              type="button"
              className="admin-btn cash-search-arrow"
              disabled={hitIndex >= hits.length - 1 || hits.length < 2}
              onClick={() => goToHit(hits, hitIndex + 1)}
              aria-label="Следующая запись"
            >
              →
            </button>
            <span className="cash-search-note">
              {hits.length > 0 ? `${hitIndex + 1} из ${hits.length}` : (searchNote ?? "")}
            </span>
          </div>
        </div>

        {cardHolder && (
          <div className="cash-card-banner">
            Личная карта: <strong>{cardHolder.name}</strong> — остаток на сегодня:{" "}
            <strong>{book?.card_balance_today != null ? money(book.card_balance_today) : "—"}</strong>
            <span className="cash-card-banner-note">
              (по записям всех доступных вам касс; ниже — движение за выбранный период)
            </span>
          </div>
        )}

        <div className="cash-summary">
          <div className="cash-balance cash-balance--opening">
            <span className="cash-balance-label">Остаток на начало</span>
            <strong className="cash-balance-value">{book ? money(book.opening) : "—"}</strong>
          </div>

          <div className="cash-actions">
            {(
              [
                { kind: "cash_in", className: "cash-action cash-action--cash-in", label: "Приход НАЛ" },
                { kind: "card_in", className: "cash-action cash-action--card-in", label: "Приход КАРТА" },
                { kind: "cash_out", className: "cash-action cash-action--cash-out", label: "Расход НАЛ" },
              ] as const
            ).map((action) => (
              <button
                key={action.kind}
                type="button"
                className={action.className}
                disabled={!workshopId || !canAdd}
                title={canAdd ? undefined : "Без права «Корректировка кассы» — только за сегодняшний день"}
                onClick={() => setDialog({ entry: null, kind: action.kind })}
              >
                {action.label}
              </button>
            ))}
          </div>

          <div className="cash-balance cash-balance--closing">
            <span className="cash-balance-label">Остаток на конец</span>
            <strong className="cash-balance-value">{book ? money(book.closing) : "—"}</strong>
          </div>
        </div>

        <div className="cash-columns">
          {COLUMNS.map((column) => {
            const entries = entriesOf(column.kind);
            return (
              <section key={column.kind} className={`cash-column cash-column--${column.kind}`}>
                <header className="cash-column-head">
                  <h3>{column.title}</h3>
                </header>
                {entries.length === 0 ? (
                  <p className="cash-column-empty">Нет записей</p>
                ) : (
                  <ul className="cash-entries">
                    {entries.map((entry) => (
                      <li key={entry.id}>
                        <button
                          type="button"
                          id={`cash-entry-${entry.id}`}
                          className={[
                            "cash-entry",
                            entry.locked ? "cash-entry--locked" : "",
                            entry.id === foundId ? "cash-entry--found" : "",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          onClick={() => setDialog({ entry, kind: entry.kind })}
                        >
                          <span className="cash-entry-main">
                            <span className="cash-entry-head">
                              {!singleDay && <span className="cash-entry-date">{formatDay(entry.entry_date)}</span>}
                              <span className="cash-entry-wo">{entry.work_order_number ?? ""}</span>
                              {entry.personal_card && (
                                <span className="cash-entry-card" title="Личная карта">
                                  💳 {entry.card_holder_name}
                                </span>
                              )}
                            </span>
                            <span className="cash-entry-comment" title={entry.comment ?? undefined}>
                              {entry.comment ?? ""}
                            </span>
                          </span>
                          <span className="cash-entry-amount">
                            {entry.locked && <span title="Период заблокирован">🔒 </span>}
                            {formatMoney(entry.amount)}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <footer className="cash-column-foot">
                  <span>Итого</span>
                  <strong>{money(totalOf(column.kind))}</strong>
                </footer>
              </section>
            );
          })}
        </div>
      </div>

      {dialog && workshopId && (
        <CashEntryDialog
          key={dialog.entry?.id ?? `new-${dialog.kind}`}
          workshopId={workshopId}
          entry={dialog.entry}
          initialKind={dialog.kind}
          initialDate={newEntryDate}
          restricted={
            !context.can_correct && (dialog.entry?.entry_date ?? newEntryDate) !== context.today
          }
          lockFrom={lock.from}
          lockTo={lock.to}
          cardHolders={context.card_holders}
          currentEmployeeId={context.current_employee_id}
          canCorrect={context.can_correct}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null);
            void load();
          }}
        />
      )}
      </div>
    </div>
  );
}
