"use client";

import { useState } from "react";

import type { StatusHistoryItem, WorkOrderLaborLineItem, WorkOrderPartLineItem } from "@/lib/backend-api";

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
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
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

type Tab = "labor" | "parts" | "history";

export function WorkOrderLineTabs({
  labor,
  parts,
  statusHistory,
}: {
  labor: WorkOrderLaborLineItem[];
  parts: WorkOrderPartLineItem[];
  statusHistory: StatusHistoryItem[];
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
      </div>

      {tab === "labor" && (
        <div className="table-wrap">
          <table className="data-table data-table--labor">
            <thead>
              <tr>
                <th>Работа</th>
                <th className="num">Цена</th>
                <th className="num">Сумма</th>
              </tr>
            </thead>
            <tbody>
              {labor.map((line, index) => (
                <tr key={index}>
                  <td>{line.operation_name || "—"}</td>
                  <td className="num">{formatMoney(line.price)}</td>
                  <td className="num">{formatMoney(line.amount)}</td>
                </tr>
              ))}
              {labor.length === 0 && (
                <tr>
                  <td colSpan={3} className="table-empty">
                    Нет строк по работам.
                  </td>
                </tr>
              )}
            </tbody>
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
              </tr>
            </thead>
            <tbody>
              {parts.map((line, index) => (
                <tr key={index}>
                  <td>{line.item_name || "—"}</td>
                  <td className="num">{formatQuantity(line.quantity)}</td>
                  <td className="num">{formatMoney(line.price)}</td>
                  <td className="num">{formatMoney(line.amount)}</td>
                </tr>
              ))}
              {parts.length === 0 && (
                <tr>
                  <td colSpan={4} className="table-empty">
                    Нет строк по товарам.
                  </td>
                </tr>
              )}
            </tbody>
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
                const isOpen = entry.last_seen_at === null;
                const endMs = isOpen ? now : new Date(entry.last_seen_at as string).getTime();
                const durationMs = endMs - new Date(entry.first_seen_at).getTime();

                return (
                  <li
                    key={index}
                    className={isOpen ? "status-timeline-item status-timeline-item-open" : "status-timeline-item"}
                  >
                    <span className="status-timeline-dot" />
                    <div className="status-timeline-body">
                      <div className="status-timeline-head">
                        <strong>{entry.status}</strong>
                        <span className="status-timeline-duration">{formatDuration(durationMs)}</span>
                      </div>
                      <div className="status-timeline-range">
                        {formatDateTime(entry.first_seen_at)} →{" "}
                        {isOpen ? "сейчас" : formatDateTime(entry.last_seen_at as string)}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </>
      )}
    </div>
  );
}
