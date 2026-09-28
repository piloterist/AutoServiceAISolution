"use client";

import { useState } from "react";

import { workshopSourceDepartmentsApi } from "@/lib/admin-client";
import type { Workshop, WorkshopSourceDepartment } from "@/lib/backend-api";

import { AdminModal } from "./AdminModal";

type FormState = {
  workshop_id: string;
  source_department: string;
};

function emptyForm(defaultWorkshopId: string, sourceDepartment = ""): FormState {
  return { workshop_id: defaultWorkshopId, source_department: sourceDepartment };
}

function workshopLabel(workshop: Workshop): string {
  return `${workshop.department_name} — ${workshop.workshop_type}`;
}

/** Settings -> Цеха -> "Соответствие 1С": the operator-maintained mapping
 * from a raw WorkOrder.department string (as 1C actually sends it - messy,
 * workshop-type-embedded, e.g. "Кузовной цех (Каховка)") to a real Workshop
 * - see backend app/models/workshop_source_department.py for the full
 * rationale (many raw strings can map to one Workshop; a company-wide view
 * still counts unmapped revenue, but a specific-workshop filter - Cockpit's
 * "Вся компания" dropdown, per-цех reporting - only sees revenue whose
 * department string is mapped here). Same row-click-to-select shape as
 * DepartmentsTab/WorkshopsTab. */
export function WorkshopSourceDepartmentsTab({
  initialRows,
  initialUnmapped,
  workshops,
}: {
  initialRows: WorkshopSourceDepartment[];
  initialUnmapped: string[];
  workshops: Workshop[];
}) {
  const [rows, setRows] = useState(initialRows);
  const [unmapped, setUnmapped] = useState(initialUnmapped);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<WorkshopSourceDepartment | "new" | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm(workshops[0]?.id ?? ""));
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<WorkshopSourceDepartment | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const selected = rows.find((r) => r.id === selectedId) ?? null;
  const toggleSelect = (row: WorkshopSourceDepartment) => {
    setSelectedId((prev) => (prev === row.id ? null : row.id));
  };

  const openNew = (sourceDepartment = "") => {
    setForm(emptyForm(workshops[0]?.id ?? "", sourceDepartment));
    setError(null);
    setEditing("new");
  };
  const openEdit = () => {
    if (!selected) return;
    setForm({ workshop_id: selected.workshop_id, source_department: selected.source_department });
    setError(null);
    setEditing(selected);
  };
  const close = () => setEditing(null);

  const save = async () => {
    if (!form.workshop_id) return setError("Выберите цех");
    if (!form.source_department.trim()) return setError("Укажите строку из 1С");

    const payload = { workshop_id: form.workshop_id, source_department: form.source_department.trim() };

    try {
      if (editing === "new") {
        const created = await workshopSourceDepartmentsApi.create(payload);
        setRows((prev) => [...prev, created].sort((a, b) => a.source_department.localeCompare(b.source_department)));
        setUnmapped((prev) => prev.filter((v) => v !== created.source_department));
      } else if (editing) {
        const updated = await workshopSourceDepartmentsApi.update(editing.id, payload);
        setRows((prev) =>
          prev
            .map((r) => (r.id === updated.id ? updated : r))
            .sort((a, b) => a.source_department.localeCompare(b.source_department)),
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
      await workshopSourceDepartmentsApi.remove(pendingDelete.id);
      setRows((prev) => prev.filter((r) => r.id !== pendingDelete.id));
      // The just-unmapped string may well still have real closed work
      // orders under it - surface it again as a suggestion rather than
      // silently dropping it from view.
      setUnmapped((prev) =>
        prev.includes(pendingDelete.source_department) ? prev : [...prev, pendingDelete.source_department].sort(),
      );
      setSelectedId(null);
      setPendingDelete(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  return (
    <div className="card">
      <div className="admin-toolbar">
        <h2 className="chart-title">Соответствие 1С</h2>
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
          <button
            type="button"
            className="admin-btn admin-btn-primary"
            onClick={() => openNew()}
            disabled={workshops.length === 0}
            title={workshops.length === 0 ? "Сначала добавьте цех" : undefined}
          >
            + Добавить
          </button>
        </div>
      </div>

      <p className="admin-hint admin-source-department-intro">
        Здесь указывается, какой строке подразделения из 1С (как её присылает Alpha-Auto, например «Кузовной цех
        (Каховка)») соответствует какой цех в системе. Одному цеху может соответствовать несколько строк из 1С.
        Выручка со строк, не указанных здесь, всё равно попадает в общий итог «Вся компания», но не попадёт в
        сумму конкретного цеха.
      </p>

      <table className="data-table admin-data-table">
        <thead>
          <tr>
            <th>Строка из 1С</th>
            <th>Цех</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              className={row.id === selectedId ? "admin-row admin-row--selected" : "admin-row"}
              onClick={() => toggleSelect(row)}
            >
              <td>{row.source_department}</td>
              <td>{row.workshop_label}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={2} className="admin-empty-row">
                Соответствий пока нет
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {unmapped.length > 0 && (
        <div className="admin-hint">
          Ещё не размечено (встречается в заказ-нарядах, но нет цеха):
          <div className="admin-unmapped-list">
            {unmapped.map((value) => (
              <button key={value} type="button" className="admin-btn" onClick={() => openNew(value)}>
                {value}
              </button>
            ))}
          </div>
        </div>
      )}

      <AdminModal
        open={editing !== null}
        title={editing === "new" ? "Новое соответствие" : "Изменить соответствие"}
        onClose={close}
      >
        <div className="admin-form-grid">
          <div className="admin-form-field">
            <label htmlFor="source-department-value">Строка из 1С</label>
            <input
              id="source-department-value"
              value={form.source_department}
              onChange={(e) => setForm((prev) => ({ ...prev, source_department: e.target.value }))}
              autoFocus
            />
          </div>

          <div className="admin-form-field">
            <label htmlFor="source-department-workshop">Цех</label>
            <select
              id="source-department-workshop"
              value={form.workshop_id}
              onChange={(e) => setForm((prev) => ({ ...prev, workshop_id: e.target.value }))}
            >
              {workshops.map((w) => (
                <option key={w.id} value={w.id}>
                  {workshopLabel(w)}
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

      <AdminModal open={pendingDelete !== null} title="Удалить соответствие?" onClose={() => setPendingDelete(null)}>
        <p>
          Точно хотите убрать привязку «{pendingDelete?.source_department}» → «{pendingDelete?.workshop_label}»?
          Заказ-наряды с этой строкой перестанут учитываться в выручке конкретного цеха (но останутся в общем
          итоге «Вся компания»).
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
