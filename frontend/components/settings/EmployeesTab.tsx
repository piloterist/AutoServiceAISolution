"use client";

import { useMemo, useState } from "react";

import { employeesApi } from "@/lib/admin-client";
import { SPECIALTIES } from "@/lib/admin-constants";
import type { Employee, OrgDepartment, Workshop } from "@/lib/backend-api";

import { AdminModal } from "./AdminModal";

type FormState = {
  full_name: string;
  specialty: string;
  department_id: string; // "" = не выбрано
  workshop_id: string;
};

function emptyForm(): FormState {
  return { full_name: "", specialty: SPECIALTIES[0], department_id: "", workshop_id: "" };
}

function toForm(employee: Employee): FormState {
  return {
    full_name: employee.full_name,
    specialty: employee.specialty,
    department_id: employee.department_id ?? "",
    workshop_id: employee.workshop_id ?? "",
  };
}

export function EmployeesTab({
  initialEmployees,
  departments,
  workshops,
}: {
  initialEmployees: Employee[];
  departments: OrgDepartment[];
  workshops: Workshop[];
}) {
  const [employees, setEmployees] = useState(initialEmployees);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Employee | "new" | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Employee | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const selected = employees.find((e) => e.id === selectedId) ?? null;
  const toggleSelect = (employee: Employee) => {
    setSelectedId((prev) => (prev === employee.id ? null : employee.id));
  };

  const availableWorkshops = useMemo(
    () => (form.department_id ? workshops.filter((w) => w.department_id === form.department_id) : workshops),
    [workshops, form.department_id],
  );

  const openNew = () => {
    setForm(emptyForm());
    setError(null);
    setEditing("new");
  };
  const openEdit = () => {
    if (!selected) return;
    setForm(toForm(selected));
    setError(null);
    setEditing(selected);
  };
  const close = () => setEditing(null);

  const save = async () => {
    if (!form.full_name.trim()) return setError("Укажите ФИО");

    try {
      const payload = {
        full_name: form.full_name.trim(),
        specialty: form.specialty,
        department_id: form.department_id || null,
        workshop_id: form.workshop_id || null,
      };
      if (editing === "new") {
        const created = await employeesApi.create(payload);
        setEmployees((prev) => [...prev, created].sort((a, b) => a.full_name.localeCompare(b.full_name)));
      } else if (editing) {
        const updated = await employeesApi.update(editing.id, payload);
        setEmployees((prev) =>
          prev.map((e) => (e.id === updated.id ? updated : e)).sort((a, b) => a.full_name.localeCompare(b.full_name)),
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
      await employeesApi.remove(pendingDelete.id);
      setEmployees((prev) => prev.filter((e) => e.id !== pendingDelete.id));
      setSelectedId(null);
      setPendingDelete(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  return (
    <div className="card">
      <div className="admin-toolbar">
        <h2 className="chart-title">Сотрудники</h2>
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
            <th>ФИО</th>
            <th>Специальность</th>
            <th>Подразделение</th>
            <th>Цех</th>
          </tr>
        </thead>
        <tbody>
          {employees.map((employee) => (
            <tr
              key={employee.id}
              className={employee.id === selectedId ? "admin-row admin-row--selected" : "admin-row"}
              onClick={() => toggleSelect(employee)}
            >
              <td>{employee.full_name}</td>
              <td>{employee.specialty}</td>
              <td>{employee.department_name ?? "—"}</td>
              <td>{employee.workshop_label ?? "—"}</td>
            </tr>
          ))}
          {employees.length === 0 && (
            <tr>
              <td colSpan={4} className="admin-empty-row">
                Сотрудников пока нет
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <AdminModal
        open={editing !== null}
        title={editing === "new" ? "Новый сотрудник" : "Изменить сотрудника"}
        onClose={close}
      >
        <div className="admin-form-grid">
          <div className="admin-form-field">
            <label htmlFor="emp-full-name">ФИО</label>
            <input
              id="emp-full-name"
              value={form.full_name}
              onChange={(e) => setForm((prev) => ({ ...prev, full_name: e.target.value }))}
              autoFocus
            />
          </div>

          <div className="admin-form-field">
            <label htmlFor="emp-specialty">Специальность</label>
            <select
              id="emp-specialty"
              value={form.specialty}
              onChange={(e) => setForm((prev) => ({ ...prev, specialty: e.target.value }))}
            >
              {SPECIALTIES.map((specialty) => (
                <option key={specialty} value={specialty}>
                  {specialty}
                </option>
              ))}
            </select>
          </div>

          <div className="admin-form-field">
            <label htmlFor="emp-department">Подразделение</label>
            <select
              id="emp-department"
              value={form.department_id}
              onChange={(e) => setForm((prev) => ({ ...prev, department_id: e.target.value, workshop_id: "" }))}
            >
              <option value="">—</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>

          <div className="admin-form-field">
            <label htmlFor="emp-workshop">Цех</label>
            <select
              id="emp-workshop"
              value={form.workshop_id}
              onChange={(e) => setForm((prev) => ({ ...prev, workshop_id: e.target.value }))}
            >
              <option value="">—</option>
              {availableWorkshops.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.department_name} / {w.workshop_type}
                </option>
              ))}
            </select>
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

      <AdminModal open={pendingDelete !== null} title="Удалить сотрудника?" onClose={() => setPendingDelete(null)}>
        <p>
          Точно хотите удалить «{pendingDelete?.full_name}»? Данные восстановить будет невозможно.
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
