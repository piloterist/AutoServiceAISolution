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

// Backend field names, not something a non-technical user should ever see
// as-is - see backend app/services/planner_service.py's _JOB_LOGGED_FIELDS/
// _CAR_LOGGED_FIELDS (the only fields that ever reach schedule_audit_log).
// employee_id/status_id/work_order_id values themselves are already
// resolved to a name/number server-side (see endpoints/admin.py's
// _humanize_changes) - this map only relabels the field NAME.
const FIELD_LABELS: Record<string, string> = {
  work_order_id: "ЗН",
  car_description: "Автомобиль",
  vin: "VIN",
  plate: "Гос.номер",
  client_name: "Клиент",
  phone: "Телефон",
  employee_id: "Сотрудник",
  work_description: "Работы",
  job_date: "Дата",
  post_number: "Пост",
  start_time: "Начало",
  end_time: "Окончание",
  status_id: "Статус",
  status: "Статус",
  on_site: "На территории",
  stages: "Этапы работ",
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

type StageSnapshot = {
  stage_name?: string;
  // Despite the key name, this is already the employee's full name by the
  // time it reaches the frontend - the backend resolves it before sending
  // (see endpoints/admin.py's _humanize_changes), never a raw UUID.
  employee_id?: string | null;
  start_date?: string;
  end_date?: string;
};

function formatValue(field: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (field === "stages" && Array.isArray(value)) {
    const stages = value as StageSnapshot[];
    if (stages.length === 0) return "нет этапов";
    return stages
      .map((s) => {
        const range = s.start_date && s.end_date ? ` ${s.start_date}–${s.end_date}` : "";
        const who = s.employee_id ? ` (${s.employee_id})` : "";
        return `${s.stage_name ?? "?"}${range}${who}`;
      })
      .join(", ");
  }
  if (field === "on_site") return value ? "да" : "нет";
  return String(value);
}

// One line per changed field, stacked (per product ask, 2026-10-01: "каждое
// значение было-стало выводи в столбик, а не встрочку как сейчас") - a
// single audit entry with 3 changed fields is still one table row, just
// with 3 stacked lines in this one cell, not one run-together line.
function renderChanges(changes: Record<string, { old: unknown; new: unknown }>) {
  const entries = Object.entries(changes);
  if (entries.length === 0) return "—";
  return (
    <div className="audit-changes-list">
      {entries.map(([field, { old, new: next }]) => (
        <div key={field}>
          {FIELD_LABELS[field] ?? field}: {formatValue(field, old)} → {formatValue(field, next)}
        </div>
      ))}
    </div>
  );
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
            <th>RecId</th>
            <th>ЗН</th>
            <th>Автомобиль</th>
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
              <td>{entry.entity_id}</td>
              <td>{entry.work_order_number ?? "—"}</td>
              <td>{entry.car_description ?? "—"}</td>
              <td className="audit-changes-cell">{renderChanges(entry.changes)}</td>
            </tr>
          ))}
          {initialEntries.length === 0 && (
            <tr>
              <td colSpan={8} className="admin-empty-row">
                Пока нет записей
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
