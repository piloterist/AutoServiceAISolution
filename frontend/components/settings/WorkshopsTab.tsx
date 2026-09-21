"use client";

import { useState } from "react";

import { workshopsApi } from "@/lib/admin-client";
import { WORKSHOP_TYPES } from "@/lib/admin-constants";
import type { OrgDepartment, Workshop, WorkshopWrite } from "@/lib/backend-api";

import { AdminModal } from "./AdminModal";

const WEEKDAY_LABELS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

type FormState = {
  department_id: string;
  workshop_type: string;
  area: string;
  posts_count: string;
  is_default: boolean;
  start_time: string;
  end_time: string;
  working_days: number[];
};

function emptyForm(defaultDepartmentId: string): FormState {
  return {
    department_id: defaultDepartmentId,
    workshop_type: WORKSHOP_TYPES[0],
    area: "",
    posts_count: "",
    is_default: false,
    start_time: "07:00",
    end_time: "22:00",
    working_days: [0, 1, 2, 3, 4, 5],
  };
}

function toForm(workshop: Workshop): FormState {
  return {
    department_id: workshop.department_id,
    workshop_type: workshop.workshop_type,
    area: workshop.area ?? "",
    posts_count: String(workshop.posts_count),
    is_default: workshop.is_default,
    start_time: workshop.start_time.slice(0, 5),
    end_time: workshop.end_time.slice(0, 5),
    working_days: workshop.working_days,
  };
}

export function WorkshopsTab({
  initialWorkshops,
  departments,
}: {
  initialWorkshops: Workshop[];
  departments: OrgDepartment[];
}) {
  const [workshops, setWorkshops] = useState(initialWorkshops);
  const [editing, setEditing] = useState<Workshop | "new" | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm(departments[0]?.id ?? ""));
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Workshop | null>(null);

  const openNew = () => {
    setForm(emptyForm(departments[0]?.id ?? ""));
    setError(null);
    setEditing("new");
  };
  const openEdit = (workshop: Workshop) => {
    setForm(toForm(workshop));
    setError(null);
    setEditing(workshop);
  };
  const close = () => setEditing(null);

  const toggleDay = (day: number) => {
    setForm((prev) => ({
      ...prev,
      working_days: prev.working_days.includes(day)
        ? prev.working_days.filter((d) => d !== day)
        : [...prev.working_days, day].sort(),
    }));
  };

  const save = async () => {
    if (!form.department_id) return setError("Выберите подразделение");
    // Кузовной doesn't use "посты" at all (see product brief part 5 - it's
    // driven by the car list, not post columns) - the field is disabled in
    // the form for that type, so don't require a value for it either.
    const isBody = form.workshop_type === "Кузовной";
    const postsCount = isBody ? 1 : Number(form.posts_count);
    if (!isBody && (!Number.isFinite(postsCount) || postsCount <= 0)) return setError("Укажите количество постов");
    if (form.working_days.length === 0) return setError("Укажите хотя бы один рабочий день");

    const payload: WorkshopWrite = {
      department_id: form.department_id,
      workshop_type: form.workshop_type,
      area: form.area.trim() ? form.area.trim() : null,
      posts_count: postsCount,
      is_default: form.is_default,
      start_time: `${form.start_time}:00`,
      end_time: `${form.end_time}:00`,
      working_days: form.working_days,
    };

    try {
      if (editing === "new") {
        const created = await workshopsApi.create(payload);
        setWorkshops((prev) => [...prev, created]);
      } else if (editing) {
        const updated = await workshopsApi.update(editing.id, payload);
        setWorkshops((prev) => prev.map((w) => (w.id === updated.id ? updated : w)));
      }
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    await workshopsApi.remove(pendingDelete.id);
    setWorkshops((prev) => prev.filter((w) => w.id !== pendingDelete.id));
    setPendingDelete(null);
  };

  return (
    <div className="card">
      <div className="admin-toolbar">
        <h2 className="chart-title">Цеха</h2>
        <button
          type="button"
          className="admin-btn admin-btn-primary"
          onClick={openNew}
          disabled={departments.length === 0}
          title={departments.length === 0 ? "Сначала добавьте подразделение" : undefined}
        >
          + Добавить
        </button>
      </div>

      <table className="data-table admin-data-table">
        <thead>
          <tr>
            <th>Подразделение</th>
            <th>Цех</th>
            <th className="num">Площадь</th>
            <th className="num">Посты</th>
            <th>Часы работы</th>
            <th>Рабочие дни</th>
            <th>По умолчанию</th>
            <th className="admin-col-actions"></th>
          </tr>
        </thead>
        <tbody>
          {workshops.map((workshop) => (
            <tr key={workshop.id}>
              <td>{workshop.department_name}</td>
              <td>{workshop.workshop_type}</td>
              <td className="num">{workshop.area ?? "—"}</td>
              <td className="num">{workshop.workshop_type === "Кузовной" ? "—" : workshop.posts_count}</td>
              <td>
                {workshop.start_time.slice(0, 5)}–{workshop.end_time.slice(0, 5)}
              </td>
              <td>{workshop.working_days.map((d) => WEEKDAY_LABELS[d]).join(", ")}</td>
              <td>{workshop.is_default ? "Да" : "—"}</td>
              <td className="admin-row-actions">
                <button type="button" className="admin-btn-link" onClick={() => openEdit(workshop)}>
                  Изменить
                </button>
                <button
                  type="button"
                  className="admin-btn-link admin-btn-link--danger"
                  onClick={() => setPendingDelete(workshop)}
                >
                  Удалить
                </button>
              </td>
            </tr>
          ))}
          {workshops.length === 0 && (
            <tr>
              <td colSpan={8} className="admin-empty-row">
                Цехов пока нет
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <AdminModal open={editing !== null} title={editing === "new" ? "Новый цех" : "Изменить цех"} onClose={close}>
        <div className="admin-form-grid">
          <div className="admin-form-field">
            <label htmlFor="workshop-department">Подразделение</label>
            <select
              id="workshop-department"
              value={form.department_id}
              onChange={(e) => setForm((prev) => ({ ...prev, department_id: e.target.value }))}
            >
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>

          <div className="admin-form-field">
            <label htmlFor="workshop-type">Цех</label>
            <select
              id="workshop-type"
              value={form.workshop_type}
              onChange={(e) => setForm((prev) => ({ ...prev, workshop_type: e.target.value }))}
            >
              {WORKSHOP_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>

          <div className="admin-form-field">
            <label htmlFor="workshop-area">Площадь, м²</label>
            <input
              id="workshop-area"
              type="number"
              min="0"
              step="0.01"
              value={form.area}
              onChange={(e) => setForm((prev) => ({ ...prev, area: e.target.value }))}
            />
          </div>

          <div className="admin-form-field">
            <label htmlFor="workshop-posts">
              Посты {form.workshop_type === "Кузовной" && <span className="admin-hint">(не используется в кузовном цехе)</span>}
            </label>
            <input
              id="workshop-posts"
              type="number"
              min="1"
              step="1"
              value={form.posts_count}
              disabled={form.workshop_type === "Кузовной"}
              onChange={(e) => setForm((prev) => ({ ...prev, posts_count: e.target.value }))}
            />
          </div>

          <div className="admin-form-field">
            <label htmlFor="workshop-start">Начало</label>
            <input
              id="workshop-start"
              type="time"
              value={form.start_time}
              onChange={(e) => setForm((prev) => ({ ...prev, start_time: e.target.value }))}
            />
          </div>

          <div className="admin-form-field">
            <label htmlFor="workshop-end">Конец</label>
            <input
              id="workshop-end"
              type="time"
              value={form.end_time}
              onChange={(e) => setForm((prev) => ({ ...prev, end_time: e.target.value }))}
            />
          </div>
        </div>

        <div className="admin-form-field">
          <span>Рабочие дни</span>
          <div className="admin-weekday-picker">
            {WEEKDAY_LABELS.map((label, day) => (
              <label key={day} className="admin-weekday-chip">
                <input
                  type="checkbox"
                  checked={form.working_days.includes(day)}
                  onChange={() => toggleDay(day)}
                />
                {label}
              </label>
            ))}
          </div>
        </div>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={form.is_default}
            onChange={(e) => setForm((prev) => ({ ...prev, is_default: e.target.checked }))}
          />
          По умолчанию
        </label>

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

      <AdminModal open={pendingDelete !== null} title="Удалить цех?" onClose={() => setPendingDelete(null)}>
        <p>
          Точно хотите удалить «{pendingDelete?.department_name} / {pendingDelete?.workshop_type}»? Данные
          восстановить будет невозможно.
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
