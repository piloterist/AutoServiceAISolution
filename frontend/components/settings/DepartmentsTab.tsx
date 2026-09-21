"use client";

import { useState } from "react";

import { departmentsApi } from "@/lib/admin-client";
import type { OrgDepartment } from "@/lib/backend-api";

import { AdminModal } from "./AdminModal";

// Rows select on click (radio-style, one at a time) instead of carrying
// their own "Изменить/Удалить" links - a wide actions column kept getting
// clipped against the table's own width no matter how that column was
// sized (three attempts, three different real CSS bugs each time); acting
// on a selected row via toolbar buttons sidesteps the problem entirely
// instead of fighting it a fourth time.
export function DepartmentsTab({ initialDepartments }: { initialDepartments: OrgDepartment[] }) {
  const [departments, setDepartments] = useState(initialDepartments);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<OrgDepartment | "new" | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<OrgDepartment | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const selected = departments.find((d) => d.id === selectedId) ?? null;

  const toggleSelect = (department: OrgDepartment) => {
    setSelectedId((prev) => (prev === department.id ? null : department.id));
  };

  const openNew = () => {
    setName("");
    setError(null);
    setEditing("new");
  };
  const openEdit = () => {
    if (!selected) return;
    setName(selected.name);
    setError(null);
    setEditing(selected);
  };
  const close = () => setEditing(null);

  const save = async () => {
    if (!name.trim()) return setError("Укажите наименование");
    try {
      if (editing === "new") {
        const created = await departmentsApi.create(name.trim());
        setDepartments((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
      } else if (editing) {
        const updated = await departmentsApi.update(editing.id, name.trim());
        setDepartments((prev) =>
          prev.map((d) => (d.id === updated.id ? updated : d)).sort((a, b) => a.name.localeCompare(b.name)),
        );
      }
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    try {
      await departmentsApi.remove(pendingDelete.id);
      setDepartments((prev) => prev.filter((d) => d.id !== pendingDelete.id));
      setSelectedId(null);
      setPendingDelete(null);
    } catch (err) {
      // Without this, a failed delete (e.g. the backend rejecting it) left
      // the confirm dialog just sitting there with no feedback at all -
      // indistinguishable from the button not responding to clicks.
      setDeleteError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  return (
    <div className="card">
      <div className="admin-toolbar">
        <h2 className="chart-title">Подразделения</h2>
        <div className="admin-toolbar-actions">
          <button type="button" className="admin-btn" disabled={!selected} onClick={openEdit}>
            Изменить
          </button>
          <button
            type="button"
            className="admin-btn admin-btn-danger"
            disabled={!selected}
            onClick={() => {
              setDeleteError(null);
              if (selected) setPendingDelete(selected);
            }}
          >
            Удалить
          </button>
          <button type="button" className="admin-btn admin-btn-primary" onClick={openNew}>
            + Добавить
          </button>
        </div>
      </div>

      <table className="data-table admin-data-table">
        <thead>
          <tr>
            <th>Наименование</th>
          </tr>
        </thead>
        <tbody>
          {departments.map((department) => (
            <tr
              key={department.id}
              className={department.id === selectedId ? "admin-row admin-row--selected" : "admin-row"}
              onClick={() => toggleSelect(department)}
            >
              <td>{department.name}</td>
            </tr>
          ))}
          {departments.length === 0 && (
            <tr>
              <td className="admin-empty-row">Подразделений пока нет</td>
            </tr>
          )}
        </tbody>
      </table>

      <AdminModal
        open={editing !== null}
        title={editing === "new" ? "Новое подразделение" : "Изменить подразделение"}
        onClose={close}
      >
        <div className="admin-form-field">
          <label htmlFor="department-name">Наименование</label>
          <input
            id="department-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
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

      <AdminModal open={pendingDelete !== null} title="Удалить подразделение?" onClose={() => setPendingDelete(null)}>
        <p>
          Точно хотите удалить «{pendingDelete?.name}»? Данные восстановить будет невозможно.
        </p>
        {deleteError && <p className="admin-form-error">{deleteError}</p>}
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
