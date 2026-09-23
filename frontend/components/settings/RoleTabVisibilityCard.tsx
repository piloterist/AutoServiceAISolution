"use client";

import { useState } from "react";

import { roleTabVisibilityApi } from "@/lib/admin-client";
import { USER_ROLES } from "@/lib/admin-constants";
import type { RoleTabVisibility } from "@/lib/backend-api";
import { NAV_TABS, type NavTabKey } from "@/lib/nav-tabs";

import { AdminModal } from "./AdminModal";

type FormState = { role: string; visibleTabs: NavTabKey[] };

function emptyForm(takenRoles: string[]): FormState {
  const firstFree = USER_ROLES.find((r) => !takenRoles.includes(r)) ?? USER_ROLES[0];
  return { role: firstFree, visibleTabs: NAV_TABS.map((t) => t.key) };
}

function toForm(row: RoleTabVisibility): FormState {
  return { role: row.role, visibleTabs: row.visible_tabs as NavTabKey[] };
}

function tabLabels(keys: string[]): string {
  return NAV_TABS.filter((t) => keys.includes(t.key))
    .map((t) => t.label)
    .join(", ");
}

/** Settings → Пользователи → "Права доступа" - which top-nav tabs
 * (lib/nav-tabs.ts's NAV_TABS) each role can see, editable here instead of
 * hardcoded (see middleware.ts, Nav.tsx). /settings itself is deliberately
 * not one of the configurable tabs - always Admin-only, so this table can
 * never be edited into a state that locks every admin out of the page that
 * edits it. */
export function RoleTabVisibilityCard({ initialRows }: { initialRows: RoleTabVisibility[] }) {
  const [rows, setRows] = useState(initialRows);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<RoleTabVisibility | "new" | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm([]));
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<RoleTabVisibility | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const selected = rows.find((r) => r.id === selectedId) ?? null;
  const toggleSelect = (row: RoleTabVisibility) => {
    setSelectedId((prev) => (prev === row.id ? null : row.id));
  };

  const openNew = () => {
    setForm(emptyForm(rows.map((r) => r.role)));
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

  const toggleTab = (key: NavTabKey) => {
    setForm((prev) => ({
      ...prev,
      visibleTabs: prev.visibleTabs.includes(key)
        ? prev.visibleTabs.filter((k) => k !== key)
        : [...prev.visibleTabs, key],
    }));
  };

  const save = async () => {
    if (form.visibleTabs.length === 0) return setError("Отметьте хотя бы одну закладку");
    try {
      const payload = { role: form.role, visible_tabs: form.visibleTabs };
      if (editing === "new") {
        const created = await roleTabVisibilityApi.create(payload);
        setRows((prev) => [...prev, created].sort((a, b) => a.role.localeCompare(b.role)));
      } else if (editing) {
        const updated = await roleTabVisibilityApi.update(editing.id, payload);
        setRows((prev) =>
          prev.map((r) => (r.id === updated.id ? updated : r)).sort((a, b) => a.role.localeCompare(b.role)),
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
      await roleTabVisibilityApi.remove(pendingDelete.id);
      setRows((prev) => prev.filter((r) => r.id !== pendingDelete.id));
      setSelectedId(null);
      setPendingDelete(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  return (
    <div className="card" style={{ marginTop: "1.5rem" }}>
      <div className="admin-toolbar">
        <h2 className="chart-title">Права доступа</h2>
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
            <th>Роль</th>
            <th style={{ width: "70%" }}>Закладки</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              className={row.id === selectedId ? "admin-row admin-row--selected" : "admin-row"}
              onClick={() => toggleSelect(row)}
            >
              <td>{row.role}</td>
              <td>{tabLabels(row.visible_tabs) || "—"}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={2} className="admin-empty-row">
                Для всех ролей действует видимость по умолчанию (все закладки)
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <AdminModal
        open={editing !== null}
        title={editing === "new" ? "Новое правило доступа" : "Изменить правило доступа"}
        onClose={close}
      >
        <div className="admin-form-grid">
          <div className="admin-form-field">
            <label htmlFor="rtv-role">Роль</label>
            <select
              id="rtv-role"
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
            <label htmlFor="rtv-tabs">Закладки</label>
            <details id="rtv-tabs" className="admin-multiselect">
              <summary>
                {form.visibleTabs.length === NAV_TABS.length
                  ? "Все закладки"
                  : form.visibleTabs.length === 0
                    ? "Ничего не выбрано"
                    : tabLabels(form.visibleTabs)}
              </summary>
              <div className="admin-multiselect-panel">
                {NAV_TABS.map((tab) => (
                  <label key={tab.key} className="admin-multiselect-option">
                    <input
                      type="checkbox"
                      checked={form.visibleTabs.includes(tab.key)}
                      onChange={() => toggleTab(tab.key)}
                    />
                    {tab.label}
                  </label>
                ))}
              </div>
            </details>
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

      <AdminModal open={pendingDelete !== null} title="Удалить правило доступа?" onClose={() => setPendingDelete(null)}>
        <p>
          Точно хотите удалить правило для роли «{pendingDelete?.role}»? Роль вернётся к видимости по умолчанию
          (все закладки).
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
