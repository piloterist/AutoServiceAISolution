"use client";

import { useState } from "react";

import { departmentsApi } from "@/lib/admin-client";
import type { OrgDepartment } from "@/lib/backend-api";

import { AdminModal } from "./AdminModal";

export function DepartmentsTab({ initialDepartments }: { initialDepartments: OrgDepartment[] }) {
  const [departments, setDepartments] = useState(initialDepartments);
  const [editing, setEditing] = useState<OrgDepartment | "new" | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<OrgDepartment | null>(null);

  const openNew = () => {
    setName("");
    setError(null);
    setEditing("new");
  };
  const openEdit = (department: OrgDepartment) => {
    setName(department.name);
    setError(null);
    setEditing(department);
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
    await departmentsApi.remove(pendingDelete.id);
    setDepartments((prev) => prev.filter((d) => d.id !== pendingDelete.id));
    setPendingDelete(null);
  };

  return (
    <div className="card">
      <div className="admin-toolbar">
        <h2 className="chart-title">Подразделения</h2>
        <button type="button" className="admin-btn admin-btn-primary" onClick={openNew}>
          + Добавить
        </button>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Наименование</th>
            <th className="admin-col-actions"></th>
          </tr>
        </thead>
        <tbody>
          {departments.map((department) => (
            <tr key={department.id}>
              <td>{department.name}</td>
              <td className="admin-row-actions">
                <button type="button" className="admin-btn-link" onClick={() => openEdit(department)}>
                  Изменить
                </button>
                <button
                  type="button"
                  className="admin-btn-link admin-btn-link--danger"
                  onClick={() => setPendingDelete(department)}
                >
                  Удалить
                </button>
              </td>
            </tr>
          ))}
          {departments.length === 0 && (
            <tr>
              <td colSpan={2} className="admin-empty-row">
                Подразделений пока нет
              </td>
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
