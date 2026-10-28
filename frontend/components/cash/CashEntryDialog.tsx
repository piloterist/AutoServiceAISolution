"use client";

import { useEffect, useRef, useState } from "react";

import { CashHistoryModal } from "@/components/cash/CashHistoryModal";
import { AdminModal } from "@/components/settings/AdminModal";
import type {
  AuditLogEntry,
  CashCardHolder,
  CashEntry,
  CashKind,
  CashWorkOrder,
} from "@/lib/backend-api";
import {
  createCashEntryClient,
  getCashEntryHistoryClient,
  searchCashWorkOrdersClient,
  updateCashEntryClient,
} from "@/lib/cash-client";
import { formatDay, formatMoment, formatMoney, formatMoneyInput, padMoneyInput, parseMoney } from "@/lib/money";

export const KIND_LABELS: Record<CashKind, string> = {
  cash_in: "Приход НАЛ",
  card_in: "Приход КАРТА",
  cash_out: "Расход НАЛ",
};

/** "Заказ-наряд" field: a drop-down of this cash desk's work orders of the
 * last 100 days that narrows as you type (number, car, VIN, customer), or - if
 * the order is not there - a number typed by hand. Picking one remembers the
 * real work order; typing again after a pick turns it back into plain text. */
function WorkOrderPicker({
  workshopId,
  text,
  disabled,
  onChange,
}: {
  workshopId: string;
  text: string;
  disabled: boolean;
  onChange: (text: string, picked: CashWorkOrder | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<CashWorkOrder[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      searchCashWorkOrdersClient(workshopId, text.trim())
        .then((found) => {
          if (!cancelled) setResults(found);
        })
        .catch(() => {
          if (!cancelled) setResults([]);
        });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, text, workshopId]);

  useEffect(() => {
    if (!open) return;
    const onOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onOutside);
    return () => document.removeEventListener("mousedown", onOutside);
  }, [open]);

  return (
    <div className="admin-form-field planner-autocomplete" ref={containerRef}>
      <label htmlFor="cash-wo">Заказ-наряд</label>
      <input
        id="cash-wo"
        value={text}
        disabled={disabled}
        onChange={(event) => {
          onChange(event.target.value, null);
          setOpen(true);
        }}
        onClick={() => setOpen(true)}
        placeholder="Выберите из списка, начните вводить или впишите номер вручную"
        autoComplete="off"
      />
      {open && results.length > 0 && (
        <ul className="planner-autocomplete-list">
          {results.map((workOrder) => (
            <li key={workOrder.id}>
              <button
                type="button"
                onClick={() => {
                  onChange(workOrder.external_number, workOrder);
                  setOpen(false);
                }}
              >
                <span className="planner-autocomplete-number">{workOrder.external_number}</span>
                <span className="planner-autocomplete-detail">
                  {workOrder.vehicle_description ?? "—"} · {workOrder.customer_name ?? "—"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The entry dialog (product ask, 2026-10-24): the same window creates a new
 * entry and edits an existing one. Only three fields (product ask,
 * 2026-10-24): заказ-наряд (optional), комментарий (several lines), сумма (with
 * thousand separators and two decimals). The раздел is fixed by the button that
 * opened it and the date is the selected day - neither can be changed here.
 * Editing: an amount of 0 deletes the entry; who created and
 * last changed it and when are shown; "История изменений" opens the system log
 * narrowed to this entry - and shows nothing at all for users without access
 * to Settings. An entry inside the locked period is shown read-only. */
export function CashEntryDialog({
  workshopId,
  entry,
  initialKind,
  initialDate,
  lockFrom,
  lockTo,
  restricted,
  cardHolders,
  currentEmployeeId,
  canCorrect,
  onClose,
  onSaved,
}: {
  workshopId: string;
  entry: CashEntry | null;
  initialKind: CashKind;
  initialDate: string;
  lockFrom: string | null;
  lockTo: string | null;
  // No "Корректировка кассы" right and the entry's day is not today.
  restricted: boolean;
  // The employees a personal card can be tied to, the one linked to the acting user
  // (the default) and whether the user may pick another ("Корректировка кассы").
  cardHolders: CashCardHolder[];
  currentEmployeeId: string | null;
  canCorrect: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  // Fixed: the section comes from the button that opened the dialog (or the
  // entry itself), the date from the selected day (or the entry itself).
  const kind: CashKind = entry?.kind ?? initialKind;
  const date = entry?.entry_date ?? initialDate;
  const [workOrderText, setWorkOrderText] = useState(entry?.work_order_number ?? "");
  const [workOrderId, setWorkOrderId] = useState<string | null>(entry?.work_order_id ?? null);
  const [comment, setComment] = useState(entry?.comment ?? "");
  const [amountText, setAmountText] = useState(entry ? formatMoney(entry.amount).replace(/ /g, " ") : "");
  // "Личная карта" - only for Приход НАЛ / Расход НАЛ.
  const cardAllowed = kind !== "card_in";
  const [personalCard, setPersonalCard] = useState(entry?.personal_card ?? false);
  const [holderId, setHolderId] = useState(
    entry?.card_holder_id ??
      (currentEmployeeId && cardHolders.some((h) => h.id === currentEmployeeId) ? currentEmployeeId : ""),
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState<AuditLogEntry[] | null>(null);

  const inLock = (day: string) => lockFrom !== null && lockTo !== null && day >= lockFrom && day <= lockTo;
  // Read-only if the entry already sits in the locked period; picking a locked
  // date is refused on save (with the server's message).
  const lockedEntry = Boolean(entry?.locked) || (entry !== null && inLock(entry.entry_date));
  const readOnly = lockedEntry || restricted;

  const save = async () => {
    setError(null);
    const amount = parseMoney(amountText);
    if (amount === null || (!entry && amount <= 0)) {
      setError(entry ? "Введите сумму (0 — удалить запись)" : "Введите сумму больше нуля");
      return;
    }
    if (entry && amount === 0 && !window.confirm("Сумма 0 — запись будет удалена. Продолжить?")) return;

    const payload = {
      workshop_id: workshopId,
      entry_date: date,
      kind,
      amount: amount.toFixed(2),
      comment: comment.trim() || null,
      work_order_id: workOrderId,
      work_order_number: workOrderText.trim() || null,
      personal_card: cardAllowed && personalCard,
      card_holder_id: cardAllowed && personalCard ? holderId || null : null,
    };
    setSaving(true);
    try {
      if (entry) await updateCashEntryClient(entry.id, payload);
      else await createCashEntryClient(payload);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  // Opens only if the log could actually be read: a user without access to
  // Settings gets a refusal from the server and simply sees nothing happen.
  const openHistory = () => {
    if (!entry) return;
    getCashEntryHistoryClient(entry.id)
      .then(setHistory)
      .catch(() => undefined);
  };

  return (
    <>
      <AdminModal
        open
        title={`${KIND_LABELS[kind]} · ${formatDay(date)}`}
        onClose={onClose}
      >
        <div className={`admin-form-grid cash-dialog cash-dialog--${kind}`}>
          {lockedEntry && (
            <p className="admin-form-error">
              Дата {formatDay(date)} в заблокированном периоде — запись нельзя изменить.
            </p>
          )}
          {restricted && !lockedEntry && (
            <p className="admin-form-error">
              Записи за другие дни может менять только пользователь с правом «Корректировка кассы».
            </p>
          )}

          <WorkOrderPicker
            workshopId={workshopId}
            text={workOrderText}
            disabled={readOnly}
            onChange={(text, picked) => {
              setWorkOrderText(text);
              setWorkOrderId(picked?.id ?? null);
            }}
          />

          <div className="admin-form-field">
            <label htmlFor="cash-comment">Комментарий</label>
            <textarea
              id="cash-comment"
              rows={6}
              value={comment}
              disabled={readOnly}
              onChange={(event) => setComment(event.target.value)}
            />
          </div>

          {cardAllowed && (
            <div className="admin-form-field">
              <div className="cash-card-row">
                <label className="settings-checkbox cash-card-check">
                  <input
                    type="checkbox"
                    checked={personalCard}
                    disabled={readOnly}
                    onChange={(event) => setPersonalCard(event.target.checked)}
                  />
                  Личная карта
                </label>
                <label htmlFor="cash-card-holder" className="cash-card-label">
                  Сотрудник
                </label>
                <select
                  id="cash-card-holder"
                  className="cash-card-select"
                  value={holderId}
                  disabled={readOnly || !personalCard || !canCorrect}
                  onChange={(event) => setHolderId(event.target.value)}
                >
                  <option value="">—</option>
                  {cardHolders.map((holder) => (
                    <option key={holder.id} value={holder.id}>
                      {holder.name}
                    </option>
                  ))}
                  {entry?.card_holder_id && !cardHolders.some((h) => h.id === entry.card_holder_id) && (
                    <option value={entry.card_holder_id}>{entry.card_holder_name}</option>
                  )}
                </select>
              </div>
              {personalCard && !canCorrect && (
                <span className="settings-description">
                  {holderId
                    ? "Сотрудника может менять только пользователь с правом «Корректировка кассы»."
                    : "Ваш пользователь не связан с сотрудником-мастером: попросите кассира внести запись."}
                </span>
              )}
            </div>
          )}

          <div className="admin-form-field">
            <label htmlFor="cash-amount">Сумма, ₽</label>
            <input
              id="cash-amount"
              className="cash-amount-input"
              inputMode="decimal"
              value={amountText}
              disabled={readOnly}
              placeholder="0,00"
              onChange={(event) => setAmountText(formatMoneyInput(event.target.value))}
              onBlur={() => setAmountText((text) => padMoneyInput(text))}
            />
            {entry && !readOnly && (
              <span className="settings-description">Чтобы удалить запись, обнулите сумму (0).</span>
            )}
          </div>

          {entry && (
            <div className="cash-dialog-meta">
              <div>
                Создано: <strong>{entry.created_by_name}</strong>, {formatMoment(entry.created_at)}
              </div>
              {entry.updated_at && entry.updated_by_name && (
                <div>
                  Изменено: <strong>{entry.updated_by_name}</strong>, {formatMoment(entry.updated_at)}
                </div>
              )}
            </div>
          )}

          {entry && (
            <button type="button" className="admin-btn cash-history-btn" onClick={openHistory}>
              История изменений
            </button>
          )}

          {error && <p className="admin-form-error">{error}</p>}
        </div>

        <div className="admin-form-actions">
          <span className="admin-form-actions-spacer" />
          <button type="button" className="admin-btn" onClick={onClose}>
            {readOnly ? "Закрыть" : "Отмена"}
          </button>
          {!readOnly && (
            <button type="button" className="admin-btn admin-btn-primary" onClick={save} disabled={saving}>
              {saving ? "Сохранение…" : "Ок"}
            </button>
          )}
        </div>
      </AdminModal>

      {history && <CashHistoryModal entries={history} onClose={() => setHistory(null)} />}
    </>
  );
}
