"use client";

import { useMemo, useState } from "react";

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

// Plain-text version of renderChanges above, for the "Что изменилось"
// column's own filter - lets a search for a field name (e.g. "Статус") or
// an old/new value (e.g. "Готова") match, same as what's actually printed
// on screen.
function changesSearchText(changes: Record<string, { old: unknown; new: unknown }>): string {
  return Object.entries(changes)
    .map(([field, { old, new: next }]) => `${FIELD_LABELS[field] ?? field} ${formatValue(field, old)} ${formatValue(field, next)}`)
    .join(" ");
}

type ColumnKey =
  | "when"
  | "who"
  | "action"
  | "entity_type"
  | "entity_id"
  | "work_order_number"
  | "car_description"
  | "changes";

const COLUMNS: { key: ColumnKey; label: string }[] = [
  { key: "when", label: "Когда" },
  { key: "who", label: "Кто" },
  { key: "action", label: "Действие" },
  { key: "entity_type", label: "Объект" },
  { key: "entity_id", label: "RecId" },
  { key: "work_order_number", label: "ЗН" },
  { key: "car_description", label: "Автомобиль" },
  { key: "changes", label: "Что изменилось" },
];

// Searchable text per column, per entry - matches exactly what's rendered
// on screen for every column except "changes" (its own display is JSX, see
// changesSearchText above for the plain-text equivalent).
function columnText(entry: AuditLogEntry): Record<ColumnKey, string> {
  return {
    when: formatDateTime(entry.created_at),
    who: entry.actor_name,
    action: ACTION_LABELS[entry.action] ?? entry.action,
    entity_type: ENTITY_TYPE_LABELS[entry.entity_type] ?? entry.entity_type,
    entity_id: entry.entity_id,
    work_order_number: entry.work_order_number ?? "",
    car_description: entry.car_description ?? "",
    changes: changesSearchText(entry.changes),
  };
}

/** Read-only - see backend app/models/schedule_audit_log.py. Empty until
 * the Planner's own write endpoints exist and start logging to it. */
export function AuditLogTab({ initialEntries }: { initialEntries: AuditLogEntry[] }) {
  // Per-column text filters (product ask, 2026-10-04: "фильтр по каждому
  // полю... текстовый, как на листе с заказ-нарядами") - same plain
  // substring/case-insensitive match as WorkOrdersTable's own columnFilters,
  // just against this table's own column text (see columnText above).
  const [columnFilters, setColumnFilters] = useState<Record<ColumnKey, string>>(() => ({
    when: "",
    who: "",
    action: "",
    entity_type: "",
    entity_id: "",
    work_order_number: "",
    car_description: "",
    changes: "",
  }));

  const filteredEntries = useMemo(() => {
    return initialEntries.filter((entry) => {
      const text = columnText(entry);
      return COLUMNS.every(({ key }) => {
        const filterValue = columnFilters[key].trim().toLowerCase();
        return !filterValue || text[key].toLowerCase().includes(filterValue);
      });
    });
  }, [initialEntries, columnFilters]);

  return (
    <div className="card">
      <h2 className="chart-title">Логи изменений</h2>
      <p className="settings-hint" style={{ marginBottom: "0.75rem" }}>
        Изменения и удаления записей в планировщике цехов (появятся здесь после включения планировщика).
        Страница не обновляется сама — если недавно что-то поменялось, перезагрузите её.
      </p>

      <table className="data-table admin-data-table">
        <thead>
          <tr>
            {COLUMNS.map((col) => (
              <th key={col.key}>{col.label}</th>
            ))}
          </tr>
          <tr className="filter-row">
            {COLUMNS.map((col) => (
              <td key={col.key}>
                <input
                  type="text"
                  value={columnFilters[col.key]}
                  onChange={(event) =>
                    setColumnFilters((prev) => ({ ...prev, [col.key]: event.target.value }))
                  }
                  placeholder="Фильтр"
                  aria-label={`Фильтр по полю ${col.label}`}
                />
              </td>
            ))}
          </tr>
        </thead>
        <tbody>
          {filteredEntries.map((entry) => (
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
          {initialEntries.length > 0 && filteredEntries.length === 0 && (
            <tr>
              <td colSpan={8} className="admin-empty-row">
                Ничего не найдено по этому фильтру
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
