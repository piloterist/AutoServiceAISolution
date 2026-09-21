"use client";

import { useState } from "react";

import { slesarkaStatusesApi } from "@/lib/admin-client";
import type { SlesarkaStatus } from "@/lib/backend-api";

import { AdminModal } from "./AdminModal";

// "Статус выбирается из списка, пока сделай Запись, В работе, Готова,
// Отмена" - a closed set for now (seeded by the migration), not free text;
// the add form offers whichever of these aren't already in use (name is
// unique on the backend).
const STATUS_NAME_OPTIONS = ["Запись", "В работе", "Готова", "Отмена"];

const COLOR_PALETTE = [
  "#5b6b82",
  "#e59a0c",
  "#17924a",
  "#d83232",
  "#2563eb",
  "#9333ea",
  "#0d9488",
  "#db2777",
  "#65a30d",
  "#78716c",
];

export function SlesarkaStatusesTab({ initialStatuses }: { initialStatuses: SlesarkaStatus[] }) {
  const [statuses, setStatuses] = useState(initialStatuses);
  const [editing, setEditing] = useState<SlesarkaStatus | "new" | null>(null);
  const [name, setName] = useState("");
  const [color, setColor] = useState(COLOR_PALETTE[0]);
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SlesarkaStatus | null>(null);

  const usedNames = new Set(statuses.map((s) => s.name));
  const availableNames = STATUS_NAME_OPTIONS.filter(
    (candidate) => !usedNames.has(candidate) || (editing !== "new" && editing?.name === candidate),
  );

  const openNew = () => {
    setName(availableNames[0] ?? "");
    setColor(COLOR_PALETTE[0]);
    setError(null);
    setEditing("new");
  };
  const openEdit = (status: SlesarkaStatus) => {
    setName(status.name);
    setColor(status.color);
    setError(null);
    setEditing(status);
  };
  const close = () => setEditing(null);

  const save = async () => {
    if (!name) return setError("Выберите статус");
    try {
      if (editing === "new") {
        const created = await slesarkaStatusesApi.create(name, color);
        setStatuses((prev) => [...prev, created]);
      } else if (editing) {
        const updated = await slesarkaStatusesApi.update(editing.id, name, color);
        setStatuses((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      }
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    await slesarkaStatusesApi.remove(pendingDelete.id);
    setStatuses((prev) => prev.filter((s) => s.id !== pendingDelete.id));
    setPendingDelete(null);
  };

  return (
    <div className="card">
      <div className="admin-toolbar">
        <h2 className="chart-title">Статусы слесарки</h2>
        <button
          type="button"
          className="admin-btn admin-btn-primary"
          onClick={openNew}
          disabled={availableNames.length === 0}
        >
          + Добавить
        </button>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Статус</th>
            <th>Цвет</th>
            <th className="admin-col-actions"></th>
          </tr>
        </thead>
        <tbody>
          {statuses.map((status) => (
            <tr key={status.id}>
              <td>{status.name}</td>
              <td>
                <span className="admin-color-dot" style={{ background: status.color }} />
                {status.color}
              </td>
              <td className="admin-row-actions">
                <button type="button" className="admin-btn-link" onClick={() => openEdit(status)}>
                  Изменить
                </button>
                <button
                  type="button"
                  className="admin-btn-link admin-btn-link--danger"
                  onClick={() => setPendingDelete(status)}
                >
                  Удалить
                </button>
              </td>
            </tr>
          ))}
          {statuses.length === 0 && (
            <tr>
              <td colSpan={3} className="admin-empty-row">
                Статусов пока нет
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <AdminModal
        open={editing !== null}
        title={editing === "new" ? "Новый статус" : "Изменить статус"}
        onClose={close}
      >
        <div className="admin-form-field">
          <label htmlFor="status-name">Статус</label>
          <select id="status-name" value={name} onChange={(e) => setName(e.target.value)}>
            {availableNames.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="admin-form-field">
          <span>Цвет</span>
          <div className="admin-swatches">
            {COLOR_PALETTE.map((swatch) => (
              <button
                key={swatch}
                type="button"
                className={swatch === color ? "admin-swatch admin-swatch--on" : "admin-swatch"}
                style={{ background: swatch }}
                onClick={() => setColor(swatch)}
                aria-label={swatch}
              />
            ))}
          </div>
        </div>

        {error && <p className="admin-form-error">{error}</p>}
        <div className="admin-form-actions">
          <span className="admin-form-actions-spacer" />
          <button type="button" className="admin-btn" onClick={close}>
            Отмена
          </button>
          <button type="button" className="admin-btn admin-btn-primary" onClick={save}>
            Сохранить
          </button>
        </div>
      </AdminModal>

      <AdminModal open={pendingDelete !== null} title="Удалить статус?" onClose={() => setPendingDelete(null)}>
        <p>
          Точно хотите удалить «{pendingDelete?.name}»? Данные восстановить будет невозможно.
        </p>
        <div className="admin-form-actions">
          <span className="admin-form-actions-spacer" />
          <button type="button" className="admin-btn" onClick={() => setPendingDelete(null)}>
            Отмена
          </button>
          <button type="button" className="admin-btn admin-btn-danger" onClick={confirmDelete}>
            Удалить
          </button>
        </div>
      </AdminModal>
    </div>
  );
}
