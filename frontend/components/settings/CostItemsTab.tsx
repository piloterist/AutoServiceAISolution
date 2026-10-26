"use client";

import { useEffect, useState } from "react";

import type { CostItem } from "@/lib/backend-api";

import { AdminModal } from "./AdminModal";

async function api<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, { cache: "no-store", ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(typeof body.error === "string" ? body.error : `Ошибка запроса: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const jsonHeaders = { "Content-Type": "application/json" };

/** Настройки -> Финансы: справочник статей затрат (product ask, 2026-10-26) -
 * the rows of Финансы -> Расходы. Two fields: the name and an active flag;
 * an inactive item stays on the Расходы table, locked. */
export function CostItemsTab() {
  const [items, setItems] = useState<CostItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<CostItem | "new" | null>(null);
  const [name, setName] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<CostItem | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    api<CostItem[]>("/api/admin/cost-items")
      .then(setItems)
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Не удалось загрузить"))
      .finally(() => setLoading(false));
  }, []);

  const selected = items.find((i) => i.id === selectedId) ?? null;

  // Order by dragging rows (product ask, 2026-10-26): drop a row onto another
  // one to put it there; the new order is saved at once.
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);

  const dropOn = async (targetId: string) => {
    const movedId = dragId;
    setDragId(null);
    setOverId(null);
    if (!movedId || movedId === targetId) return;
    const before = items;
    const from = before.findIndex((i) => i.id === movedId);
    const to = before.findIndex((i) => i.id === targetId);
    if (from < 0 || to < 0) return;
    const next = [...before];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setItems(next);
    try {
      await api<CostItem[]>("/api/admin/cost-items/order", {
        method: "PUT",
        headers: jsonHeaders,
        body: JSON.stringify({ ids: next.map((i) => i.id) }),
      });
      setLoadError(null);
    } catch (err) {
      setItems(before);
      setLoadError(err instanceof Error ? err.message : "Не удалось сохранить порядок");
    }
  };

  const openNew = () => {
    setName("");
    setIsActive(true);
    setError(null);
    setEditing("new");
  };
  const openEdit = () => {
    if (!selected) return;
    setName(selected.name);
    setIsActive(selected.is_active);
    setError(null);
    setEditing(selected);
  };
  const close = () => setEditing(null);

  const save = async () => {
    if (!name.trim()) return setError("Введите наименование статьи затрат");
    try {
      const payload = { name: name.trim(), is_active: isActive };
      if (editing === "new") {
        const created = await api<CostItem>("/api/admin/cost-items", {
          method: "POST",
          headers: jsonHeaders,
          body: JSON.stringify(payload),
        });
        setItems((prev) => [...prev, created]); // new items go to the end
      } else if (editing) {
        const updated = await api<CostItem>(`/api/admin/cost-items/${editing.id}`, {
          method: "PUT",
          headers: jsonHeaders,
          body: JSON.stringify(payload),
        });
        setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
      }
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    try {
      await api<void>(`/api/admin/cost-items/${pendingDelete.id}`, { method: "DELETE" });
      setItems((prev) => prev.filter((i) => i.id !== pendingDelete.id));
      setSelectedId(null);
      setPendingDelete(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  return (
    <div className="org-group">
      <h2 className="org-group-title">Статьи затрат</h2>
      <p className="settings-description">
        Порядок строк задаётся перетаскиванием: возьмите строку за значок ⋮⋮ и перенесите на нужное место. В
        этом же порядке статьи выводятся на закладке «Расходы».
      </p>
      {loadError && <p className="admin-form-error">{loadError}</p>}
      <div className="org-group-body">
        <div className="org-group-table">
          <table className="data-table admin-data-table">
            <thead>
              <tr>
                <th style={{ width: "2rem" }} />
                <th>Наименование статьи затрат</th>
                <th>Активна</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.id}
                  draggable
                  onDragStart={() => setDragId(item.id)}
                  onDragOver={(event) => {
                    event.preventDefault();
                    if (overId !== item.id) setOverId(item.id);
                  }}
                  onDrop={() => void dropOn(item.id)}
                  onDragEnd={() => {
                    setDragId(null);
                    setOverId(null);
                  }}
                  className={[
                    item.id === selectedId ? "admin-row admin-row--selected" : "admin-row",
                    item.id === dragId ? "cost-item-row--dragging" : "",
                    item.id === overId && dragId && dragId !== item.id ? "cost-item-row--over" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => setSelectedId((prev) => (prev === item.id ? null : item.id))}
                >
                  <td className="cost-item-handle" title="Перетащите, чтобы изменить порядок">
                    ⋮⋮
                  </td>
                  <td>{item.name}</td>
                  <td>{item.is_active ? "Да" : "Нет"}</td>
                </tr>
              ))}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={3} className="admin-empty-row">
                    Статей затрат пока нет
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="org-group-actions">
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

      <AdminModal
        open={editing !== null}
        title={editing === "new" ? "Новая статья затрат" : "Изменить статью затрат"}
        onClose={close}
      >
        <div className="admin-form-field">
          <label htmlFor="cost-item-name">Наименование статьи затрат</label>
          <input id="cost-item-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <label className="settings-checkbox">
          <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
          Активна
        </label>
        <p className="settings-description">
          У неактивной статьи значения на закладке «Расходы» нельзя менять, внесённые суммы остаются и
          входят в итог.
        </p>
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

      <AdminModal open={pendingDelete !== null} title="Удалить статью?" onClose={() => setPendingDelete(null)}>
        <p>Точно хотите удалить «{pendingDelete?.name}»?</p>
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
