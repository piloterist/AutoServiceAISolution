"use client";

import { AdminModal } from "@/components/settings/AdminModal";
import type { AuditLogEntry } from "@/lib/backend-api";
import { formatDay, formatMoment, formatMoney } from "@/lib/money";

const ACTION_LABELS: Record<string, string> = {
  create: "Создание",
  update: "Изменение",
  delete: "Удаление",
};

const FIELD_LABELS: Record<string, string> = {
  workshop: "Касса",
  kind: "Раздел",
  entry_date: "Дата",
  amount: "Сумма",
  comment: "Комментарий",
  work_order_number: "Заказ-наряд",
};

function showValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (field === "amount") return `${formatMoney(String(value))} ₽`;
  if (field === "entry_date") return formatDay(String(value));
  return String(value);
}

/** The change log of one cash entry - the same system log Settings shows,
 * narrowed to this record (the dialog's "История изменений" button). */
export function CashHistoryModal({
  entries,
  onClose,
}: {
  entries: AuditLogEntry[];
  onClose: () => void;
}) {
  return (
    <AdminModal open title="История изменений записи" onClose={onClose} wide closeOnBackdropClick>
      {entries.length === 0 ? (
        <p className="telephony-events-status">Изменений не найдено</p>
      ) : (
        <table className="data-table cash-history-table">
          <thead>
            <tr>
              <th>Когда</th>
              <th>Кто</th>
              <th>Действие</th>
              <th>Что изменилось</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.id}>
                <td>{formatMoment(entry.created_at)}</td>
                <td>{entry.actor_name}</td>
                <td>{ACTION_LABELS[entry.action] ?? entry.action}</td>
                <td>
                  <ul className="cash-history-changes">
                    {Object.entries(entry.changes).map(([field, diff]) => (
                      <li key={field}>
                        <span className="cash-history-field">{FIELD_LABELS[field] ?? field}:</span>{" "}
                        {entry.action === "create"
                          ? showValue(field, diff.new)
                          : entry.action === "delete"
                            ? showValue(field, diff.old)
                            : `${showValue(field, diff.old)} → ${showValue(field, diff.new)}`}
                      </li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </AdminModal>
  );
}
