"use client";

import type { AuditLogEntry } from "@/lib/backend-api";

const ACTION_LABELS: Record<string, string> = {
  create: "Создание",
  update: "Изменение",
  delete: "Удаление",
};

const ENTITY_TYPE_LABELS: Record<string, string> = {
  workshop_job: "Запись слесарки",
  body_car: "Автомобиль в кузовном цехе",
  body_car_stage: "Этап работ",
};

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatChanges(changes: Record<string, { old: unknown; new: unknown }>): string {
  const entries = Object.entries(changes);
  if (entries.length === 0) return "—";
  return entries.map(([field, { old, new: next }]) => `${field}: ${old ?? "—"} → ${next ?? "—"}`).join("; ");
}

/** Read-only - see backend app/models/schedule_audit_log.py. Empty until
 * the Planner's own write endpoints exist and start logging to it. */
export function AuditLogTab({ initialEntries }: { initialEntries: AuditLogEntry[] }) {
  return (
    <div className="card">
      <h2 className="chart-title">Логи изменений</h2>
      <p className="settings-hint" style={{ marginBottom: "0.75rem" }}>
        Изменения и удаления записей в планировщике цехов (появятся здесь после включения планировщика).
      </p>

      <table className="data-table admin-data-table">
        <thead>
          <tr>
            <th>Когда</th>
            <th>Кто</th>
            <th>Действие</th>
            <th>Объект</th>
            <th>Что изменилось</th>
          </tr>
        </thead>
        <tbody>
          {initialEntries.map((entry) => (
            <tr key={entry.id}>
              <td>{formatDateTime(entry.created_at)}</td>
              <td>{entry.actor_name}</td>
              <td>{ACTION_LABELS[entry.action] ?? entry.action}</td>
              <td>{ENTITY_TYPE_LABELS[entry.entity_type] ?? entry.entity_type}</td>
              <td>{formatChanges(entry.changes)}</td>
            </tr>
          ))}
          {initialEntries.length === 0 && (
            <tr>
              <td colSpan={5} className="admin-empty-row">
                Пока нет записей
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
