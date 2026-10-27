"use client";

import { useState } from "react";

import type {
  InvoiceItem,
  PaymentEventItem,
  StatusHistoryItem,
  WorkOrderLaborLineItem,
  WorkOrderPartLineItem,
} from "@/lib/backend-api";

function formatMoney(value: string | null): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value)) + " ₽";
}

function formatQuantity(value: string | null): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 }).format(Number(value));
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDateTimeOrDash(iso: string | null): string {
  return iso ? formatDateTime(iso) : "—";
}

// "Оплачен"/"Частично оплачен"/"Не оплачен" - see backend schemas/
// work_order.py's InvoiceItem.from_model for where this exact text comes
// from (not a free enum - matching on it here is safe).
function invoiceStatusClass(status: string): string {
  if (status === "Оплачен") return "invoice-status invoice-status--paid";
  if (status === "Частично оплачен") return "invoice-status invoice-status--partial";
  return "invoice-status invoice-status--unpaid";
}

function pluralize(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return few;
  return many;
}

/** "2 дня 6 часов" / "18 часов" / "45 минут" - coarsens to the two biggest
 * units so a multi-day segment doesn't read out down to the minute. */
function formatDuration(ms: number): string {
  const totalMinutes = Math.max(0, Math.round(ms / 60_000));
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;

  if (days > 0) {
    const daysPart = `${days} ${pluralize(days, "день", "дня", "дней")}`;
    return hours > 0 ? `${daysPart} ${hours} ${pluralize(hours, "час", "часа", "часов")}` : daysPart;
  }
  if (hours > 0) {
    const hoursPart = `${hours} ${pluralize(hours, "час", "часа", "часов")}`;
    return minutes > 0
      ? `${hoursPart} ${minutes} ${pluralize(minutes, "минута", "минуты", "минут")}`
      : hoursPart;
  }
  return `${minutes} ${pluralize(minutes, "минута", "минуты", "минут")}`;
}

type DiscountLine = {
  amount: string | null;
  discount_percent: string | null;
  discount_amount: string | null;
  total_amount: string | null;
  discount_name: string | null;
};

/** The line's total after its discount; a line exported before the discount
 * was sent has none, so it shows its amount. */
function lineTotal(line: DiscountLine): number {
  return Number(line.total_amount ?? line.amount ?? 0);
}

/** The totals row of a lines table: sum before the discount, the discount
 * given, and the sum after it (product ask, 2026-10-28 - so the discount on
 * works / on parts is seen at once, not added up by hand). */
function sumLines(lines: DiscountLine[]): { amount: number; discount: number; total: number } {
  return lines.reduce(
    (acc, line) => ({
      amount: acc.amount + Number(line.amount ?? 0),
      discount: acc.discount + Number(line.discount_amount ?? 0),
      total: acc.total + lineTotal(line),
    }),
    { amount: 0, discount: 0, total: 0 },
  );
}

function formatPercent(value: string | null): string {
  if (value === null || Number(value) === 0) return "—";
  return `${Number(value).toLocaleString("ru-RU", { maximumFractionDigits: 2 })}%`;
}

type Tab = "labor" | "parts" | "history" | "payments" | "invoices";

export function WorkOrderLineTabs({
  labor,
  parts,
  statusHistory,
  paymentEvents,
  invoices,
}: {
  labor: WorkOrderLaborLineItem[];
  parts: WorkOrderPartLineItem[];
  statusHistory: StatusHistoryItem[];
  /** Real, dated payments (work_order_payment_events) - each row's date is
   * the actual 1C payment date, not when we happened to observe it. */
  paymentEvents: PaymentEventItem[];
  /** Счета на оплату linked to this work order (product ask, 2026-10-22:
   * "записывать в историю оплат, что выставлен счет такой-то на такую-то
   * сумму") - distinct from paymentEvents above: a Счёт is what was
   * billed, not a real dated money-in movement. */
  invoices: InvoiceItem[];
}) {
  const [tab, setTab] = useState<Tab>("labor");
  const now = Date.now();

  return (
    <div>
      <div className="tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "labor"}
          className={tab === "labor" ? "tab tab-active" : "tab"}
          onClick={() => setTab("labor")}
        >
          Работы ({labor.length})
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "parts"}
          className={tab === "parts" ? "tab tab-active" : "tab"}
          onClick={() => setTab("parts")}
        >
          Товары ({parts.length})
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "history"}
          className={tab === "history" ? "tab tab-active" : "tab"}
          onClick={() => setTab("history")}
        >
          История статусов ({statusHistory.length})
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "payments"}
          className={tab === "payments" ? "tab tab-active" : "tab"}
          onClick={() => setTab("payments")}
        >
          История оплат ({paymentEvents.length})
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "invoices"}
          className={tab === "invoices" ? "tab tab-active" : "tab"}
          onClick={() => setTab("invoices")}
        >
          Счета на оплату ({invoices.length})
        </button>
      </div>

      {tab === "labor" && (
        <div className="table-wrap">
          <table className="data-table data-table--labor">
            <thead>
              <tr>
                <th>Работа</th>
                <th className="num">Цена</th>
                <th className="num">Сумма</th>
                <th className="num">Скидка, %</th>
                <th className="num">Скидка, ₽</th>
                <th>Скидка (название)</th>
                <th className="num">Итого</th>
              </tr>
            </thead>
            <tbody>
              {labor.map((line, index) => (
                <tr key={index}>
                  <td>{line.operation_name || "—"}</td>
                  <td className="num">{formatMoney(line.price)}</td>
                  <td className="num">{formatMoney(line.amount)}</td>
                  <td className="num">{formatPercent(line.discount_percent)}</td>
                  <td className="num">{formatMoney(line.discount_amount)}</td>
                  <td>{line.discount_name || "—"}</td>
                  <td className="num">{formatMoney(String(lineTotal(line)))}</td>
                </tr>
              ))}
              {labor.length === 0 && (
                <tr>
                  <td colSpan={7} className="table-empty">
                    Нет строк по работам.
                  </td>
                </tr>
              )}
            </tbody>
            {labor.length > 0 && (
              <tfoot>
                <tr className="lines-total-row">
                  <td>Итого по работам</td>
                  <td />
                  <td className="num">{formatMoney(String(sumLines(labor).amount))}</td>
                  <td />
                  <td className="num">{formatMoney(String(sumLines(labor).discount))}</td>
                  <td />
                  <td className="num">{formatMoney(String(sumLines(labor).total))}</td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}

      {tab === "parts" && (
        <div className="table-wrap">
          <table className="data-table data-table--parts">
            <thead>
              <tr>
                <th>Номенклатура</th>
                <th className="num">Количество</th>
                <th className="num">Цена</th>
                <th className="num">Сумма</th>
                <th className="num">Скидка, %</th>
                <th className="num">Скидка, ₽</th>
                <th>Скидка (название)</th>
                <th className="num">Итого</th>
              </tr>
            </thead>
            <tbody>
              {parts.map((line, index) => (
                <tr key={index}>
                  <td>{line.item_name || "—"}</td>
                  <td className="num">{formatQuantity(line.quantity)}</td>
                  <td className="num">{formatMoney(line.price)}</td>
                  <td className="num">{formatMoney(line.amount)}</td>
                  <td className="num">{formatPercent(line.discount_percent)}</td>
                  <td className="num">{formatMoney(line.discount_amount)}</td>
                  <td>{line.discount_name || "—"}</td>
                  <td className="num">{formatMoney(String(lineTotal(line)))}</td>
                </tr>
              ))}
              {parts.length === 0 && (
                <tr>
                  <td colSpan={8} className="table-empty">
                    Нет строк по товарам.
                  </td>
                </tr>
              )}
            </tbody>
            {parts.length > 0 && (
              <tfoot>
                <tr className="lines-total-row">
                  <td>Итого по товарам</td>
                  <td />
                  <td />
                  <td className="num">{formatMoney(String(sumLines(parts).amount))}</td>
                  <td />
                  <td className="num">{formatMoney(String(sumLines(parts).discount))}</td>
                  <td />
                  <td className="num">{formatMoney(String(sumLines(parts).total))}</td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}

      {tab === "history" && (
        <>
          {statusHistory.length === 0 ? (
            <p className="table-empty">История статусов пока не накоплена.</p>
          ) : (
            <ol className="status-timeline">
              {statusHistory.map((entry, index) => {
                // Real 1C status-change events, not stored segments - "how
                // long was it in this status" is the gap to the *next*
                // real event (or to now, for the last/current one), not a
                // separately-tracked end boundary.
                const next = statusHistory[index + 1];
                const isOpen = next === undefined;
                const endMs = isOpen ? now : new Date(next.changed_at).getTime();
                const durationMs = endMs - new Date(entry.changed_at).getTime();

                return (
                  <li
                    key={entry.version_number}
                    className={isOpen ? "status-timeline-item status-timeline-item-open" : "status-timeline-item"}
                  >
                    <span className="status-timeline-dot" />
                    <div className="status-timeline-body">
                      <div className="status-timeline-head">
                        <strong>{entry.status}</strong>
                        <span className="status-timeline-duration">{formatDuration(durationMs)}</span>
                      </div>
                      <div className="status-timeline-range">
                        {formatDateTime(entry.changed_at)} → {isOpen ? "сейчас" : formatDateTime(next.changed_at)}
                      </div>
                      {entry.author && <div className="status-timeline-author">{entry.author}</div>}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </>
      )}

      {tab === "payments" && (
        <div className="table-wrap">
          <table className="data-table data-table--payments">
            <thead>
              <tr>
                <th>Дата</th>
                <th className="num">Сумма</th>
                <th>Документ</th>
              </tr>
            </thead>
            <tbody>
              {paymentEvents.map((entry, index) => (
                <tr key={index}>
                  <td>{formatDateTime(entry.paid_at)}</td>
                  <td className="num">{formatMoney(entry.amount)}</td>
                  <td>
                    {[entry.source_document_type, entry.source_document_number]
                      .filter(Boolean)
                      .join(" ") || "—"}
                  </td>
                </tr>
              ))}
              {paymentEvents.length === 0 && (
                <tr>
                  <td colSpan={3} className="table-empty">
                    История оплат пока не накоплена.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === "invoices" && (
        <div className="table-wrap">
          <table className="data-table data-table--invoices">
            <thead>
              <tr>
                <th>Номер</th>
                <th>Дата</th>
                <th className="num">Сумма</th>
                <th className="num">Оплачено</th>
                <th className="num">Долг</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((entry, index) => (
                <tr key={index}>
                  <td>{entry.external_number || "—"}</td>
                  <td>{formatDateTimeOrDash(entry.document_date)}</td>
                  <td className="num">{formatMoney(entry.amount)}</td>
                  <td className="num">{formatMoney(entry.paid_amount)}</td>
                  <td className="num">{formatMoney(entry.debt_amount)}</td>
                  <td>
                    <span className={invoiceStatusClass(entry.status)}>{entry.status}</span>
                  </td>
                </tr>
              ))}
              {invoices.length === 0 && (
                <tr>
                  <td colSpan={6} className="table-empty">
                    Счетов на оплату по этому заказ-наряду нет.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
