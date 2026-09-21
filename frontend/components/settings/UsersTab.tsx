"use client";

import { useMemo, useState } from "react";

import { usersApi } from "@/lib/admin-client";
import { USER_ROLES } from "@/lib/admin-constants";
import type { OrgDepartment, OrgUser, Workshop } from "@/lib/backend-api";

import { AdminModal } from "./AdminModal";

type FormState = {
  full_name: string;
  login: string;
  password: string;
  role: string;
  department_id: string; // "" = не выбрано
  workshop_id: string;
};

function emptyForm(): FormState {
  return { full_name: "", login: "", password: "", role: USER_ROLES[USER_ROLES.length - 1], department_id: "", workshop_id: "" };
}

function toForm(user: OrgUser): FormState {
  return {
    full_name: user.full_name,
    login: user.login,
    password: "",
    role: user.role,
    department_id: user.department_id ?? "",
    workshop_id: user.workshop_id ?? "",
  };
}

export function UsersTab({
  initialUsers,
  departments,
  workshops,
}: {
  initialUsers: OrgUser[];
  departments: OrgDepartment[];
  workshops: Workshop[];
}) {
  const [users, setUsers] = useState(initialUsers);
  const [editing, setEditing] = useState<OrgUser | "new" | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<OrgUser | null>(null);

  const availableWorkshops = useMemo(
    () => (form.department_id ? workshops.filter((w) => w.department_id === form.department_id) : workshops),
    [workshops, form.department_id],
  );

  const openNew = () => {
    setForm(emptyForm());
    setError(null);
    setEditing("new");
  };
  const openEdit = (user: OrgUser) => {
    setForm(toForm(user));
    setError(null);
    setEditing(user);
  };
  const close = () => setEditing(null);

  const save = async () => {
    if (!form.full_name.trim()) return setError("Укажите ФИО");
    if (!form.login.trim()) return setError("Укажите логин");
    if (editing === "new" && form.password.length < 4) return setError("Пароль минимум 4 символа");
    if (form.password && form.password.length < 4) return setError("Пароль минимум 4 символа");

    try {
      if (editing === "new") {
        const created = await usersApi.create({
          full_name: form.full_name.trim(),
          login: form.login.trim(),
          password: form.password,
          role: form.role,
          department_id: form.department_id || null,
          workshop_id: form.workshop_id || null,
        });
        setUsers((prev) => [...prev, created].sort((a, b) => a.full_name.localeCompare(b.full_name)));
      } else if (editing) {
        const updated = await usersApi.update(editing.id, {
          full_name: form.full_name.trim(),
          login: form.login.trim(),
          password: form.password || null,
          role: form.role,
          department_id: form.department_id || null,
          workshop_id: form.workshop_id || null,
        });
        setUsers((prev) =>
          prev.map((u) => (u.id === updated.id ? updated : u)).sort((a, b) => a.full_name.localeCompare(b.full_name)),
        );
      }
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    await usersApi.remove(pendingDelete.id);
    setUsers((prev) => prev.filter((u) => u.id !== pendingDelete.id));
    setPendingDelete(null);
  };

  return (
    <div className="card">
      <div className="admin-toolbar">
        <h2 className="chart-title">Пользователи</h2>
        <button type="button" className="admin-btn admin-btn-primary" onClick={openNew}>
          + Добавить
        </button>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>ФИО</th>
            <th>Логин</th>
            <th>Роль</th>
            <th>Подразделение</th>
            <th className="admin-col-actions"></th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id}>
              <td>{user.full_name}</td>
              <td>{user.login}</td>
              <td>{user.role}</td>
              <td>{user.department_name ?? "—"}</td>
              <td className="admin-row-actions">
                <button type="button" className="admin-btn-link" onClick={() => openEdit(user)}>
                  Изменить
                </button>
                <button
                  type="button"
                  className="admin-btn-link admin-btn-link--danger"
                  onClick={() => setPendingDelete(user)}
                >
                  Удалить
                </button>
              </td>
            </tr>
          ))}
          {users.length === 0 && (
            <tr>
              <td colSpan={5} className="admin-empty-row">
                Пользователей пока нет
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <AdminModal
        open={editing !== null}
        title={editing === "new" ? "Новый пользователь" : "Изменить пользователя"}
        onClose={close}
      >
        <div className="admin-form-grid">
          <div className="admin-form-field">
            <label htmlFor="user-full-name">ФИО</label>
            <input
              id="user-full-name"
              value={form.full_name}
              onChange={(e) => setForm((prev) => ({ ...prev, full_name: e.target.value }))}
              autoFocus
            />
          </div>

          <div className="admin-form-field">
            <label htmlFor="user-login">Логин</label>
            <input
              id="user-login"
              value={form.login}
              onChange={(e) => setForm((prev) => ({ ...prev, login: e.target.value }))}
            />
          </div>

          <div className="admin-form-field">
            <label htmlFor="user-password">
              Пароль {editing !== "new" && <span className="admin-hint">(оставьте пустым, чтобы не менять)</span>}
            </label>
            <input
              id="user-password"
              type="password"
              value={form.password}
              onChange={(e) => setForm((prev) => ({ ...prev, password: e.target.value }))}
              autoComplete="new-password"
            />
          </div>

          <div className="admin-form-field">
            <label htmlFor="user-role">Роль</label>
            <select
              id="user-role"
              value={form.role}
              onChange={(e) => setForm((prev) => ({ ...prev, role: e.target.value }))}
            >
              {USER_ROLES.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </div>

          <div className="admin-form-field">
            <label htmlFor="user-department">Подразделение</label>
            <select
              id="user-department"
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
            <label htmlFor="user-workshop">Цех</label>
            <select
              id="user-workshop"
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

      <AdminModal open={pendingDelete !== null} title="Удалить пользователя?" onClose={() => setPendingDelete(null)}>
        <p>
          Точно хотите удалить «{pendingDelete?.full_name}»? Данные восстановить будет невозможно.
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
