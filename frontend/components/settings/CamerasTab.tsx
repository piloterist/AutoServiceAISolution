"use client";

import { useState } from "react";

import type { Camera, CameraWrite } from "@/lib/backend-api";

import { AdminModal } from "./AdminModal";

// Справочник камер: код (как у бокса и в bays.toml узла), MAC с наклейки на корпусе, модель.
// Текущий IP вручную не вводится - его находит узел на площадке по MAC и присылает сюда.

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(typeof body.error === "string" ? body.error : `Request failed: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

function formatSeen(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function videoStatus(camera: Camera): { text: string; ok: boolean | null } {
  if (camera.camera_ok === null) return { text: "узел не писал", ok: null };
  return camera.camera_ok ? { text: "видео идёт", ok: true } : { text: "нет видео", ok: false };
}

export function CamerasTab({ initialCameras }: { initialCameras: Camera[] }) {
  const [cameras, setCameras] = useState(initialCameras);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Camera | "new" | null>(null);
  const [form, setForm] = useState({ code: "", mac: "", name: "", model: "", note: "" });
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Camera | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const selected = cameras.find((c) => c.id === selectedId) ?? null;

  const openNew = () => {
    setForm({ code: "", mac: "", name: "", model: "TP-Link VIGI C440 4mm", note: "" });
    setError(null);
    setEditing("new");
  };
  const openEdit = () => {
    if (!selected) return;
    setForm({
      code: selected.code,
      mac: selected.mac,
      name: selected.name ?? "",
      model: selected.model ?? "",
      note: selected.note ?? "",
    });
    setError(null);
    setEditing(selected);
  };
  const close = () => setEditing(null);

  const save = async () => {
    if (!form.code.trim()) return setError("Укажите код камеры");
    if (!form.mac.trim()) return setError("Укажите MAC-адрес");
    const payload: CameraWrite = {
      code: form.code.trim(),
      mac: form.mac.trim(),
      name: form.name.trim() || null,
      model: form.model.trim() || null,
      note: form.note.trim() || null,
    };
    try {
      if (editing === "new") {
        const created = await request<Camera>("/api/cameras", {
          method: "POST",
          headers: JSON_HEADERS,
          body: JSON.stringify(payload),
        });
        setCameras((prev) => [...prev, created].sort((a, b) => a.code.localeCompare(b.code)));
      } else if (editing) {
        const updated = await request<Camera>(`/api/cameras/${editing.id}`, {
          method: "PUT",
          headers: JSON_HEADERS,
          body: JSON.stringify(payload),
        });
        setCameras((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
      }
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    try {
      await request<void>(`/api/cameras/${pendingDelete.id}`, { method: "DELETE" });
      setCameras((prev) => prev.filter((c) => c.id !== pendingDelete.id));
      setSelectedId(null);
      setPendingDelete(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  const field = (key: keyof typeof form, label: string, placeholder?: string) => (
    <div className="admin-form-field">
      <label htmlFor={`camera-${key}`}>{label}</label>
      <input
        id={`camera-${key}`}
        value={form[key]}
        placeholder={placeholder}
        onChange={(e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))}
      />
    </div>
  );

  return (
    <div className="org-group">
      <h2 className="org-group-title">Камеры</h2>
      <p className="admin-hint">
        MAC-адрес указан на наклейке на корпусе камеры. Узел на площадке сам находит камеру по MAC и
        присылает сюда её текущий IP; если IP сменился, подставит новый. Код камеры должен совпадать с
        кодом в <code>bays.toml</code> узла и с полем «Камера» у бокса.
      </p>
      <div className="org-group-body">
        <div className="org-group-table">
          <table className="data-table admin-data-table">
            <thead>
              <tr>
                <th>Код</th>
                <th>MAC</th>
                <th>Текущий IP</th>
                <th>Видео</th>
                <th>Модель</th>
                <th>Название / примечание</th>
              </tr>
            </thead>
            <tbody>
              {cameras.map((camera) => {
                const video = videoStatus(camera);
                return (
                  <tr
                    key={camera.id}
                    className={camera.id === selectedId ? "admin-row admin-row--selected" : "admin-row"}
                    onClick={() => setSelectedId((prev) => (prev === camera.id ? null : camera.id))}
                  >
                    <td>{camera.code}</td>
                    <td>{camera.mac}</td>
                    <td title={camera.ip_seen_at ? `найден ${formatSeen(camera.ip_seen_at)}` : undefined}>
                      {camera.ip ?? "—"}
                    </td>
                    <td style={video.ok === false ? { color: "var(--down)" } : undefined}>{video.text}</td>
                    <td>{camera.model ?? "—"}</td>
                    <td>{[camera.name, camera.note].filter(Boolean).join(" · ") || "—"}</td>
                  </tr>
                );
              })}
              {cameras.length === 0 && (
                <tr>
                  <td colSpan={6} className="admin-empty-row">
                    Камер пока нет
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
        title={editing === "new" ? "Новая камера" : "Изменить камеру"}
        onClose={close}
      >
        {field("code", "Код камеры", "cam2")}
        {field("mac", "MAC-адрес", "9C-A2-F4-DA-22-EA")}
        {field("name", "Название", "Бокс 2")}
        {field("model", "Модель")}
        {field("note", "Примечание")}
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

      <AdminModal open={pendingDelete !== null} title="Удалить камеру?" onClose={() => setPendingDelete(null)}>
        <p>
          Точно хотите удалить «{pendingDelete?.code}» из справочника? Узел перестанет искать её по MAC.
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
