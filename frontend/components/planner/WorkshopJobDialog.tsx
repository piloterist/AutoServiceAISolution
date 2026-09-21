"use client";

import { useState } from "react";

import { AdminModal } from "@/components/settings/AdminModal";
import type { PlannerWorkOrder, SlesarkaStatus, WorkshopJob, WorkshopJobWrite } from "@/lib/backend-api";
import { minutesToTime, timeToMinutes } from "@/lib/planner-time";

import { WorkOrderAutocomplete } from "./WorkOrderAutocomplete";

export type JobDraft = {
  jobId: string | null; // null = new record
  workOrderId: string | null;
  workOrderNumber: string;
  amount: string | null;
  carDescription: string;
  vin: string;
  plate: string;
  clientName: string;
  workDescription: string;
  jobDate: string;
  postNumber: number;
  startTime: string; // "HH:MM"
  endTime: string;
  normHours: string;
  statusId: string | null;
};

function timeOptions(startTime: string, endTime: string): string[] {
  const start = timeToMinutes(startTime);
  const end = timeToMinutes(endTime);
  const options: string[] = [];
  for (let m = start; m <= end; m += 30) options.push(minutesToTime(m));
  return options;
}

/** Caller must remount this with a fresh `key` per draft (e.g.
 * `draft?.jobId ?? "new"`) so opening a different record resets the form -
 * see MechanicalView's usage. */
export function WorkshopJobDialog({
  open,
  draft,
  postsCount,
  statuses,
  workshopStartTime,
  workshopEndTime,
  onClose,
  onSave,
  onDelete,
}: {
  open: boolean;
  draft: JobDraft | null;
  postsCount: number;
  statuses: SlesarkaStatus[];
  workshopStartTime: string;
  workshopEndTime: string;
  onClose: () => void;
  onSave: (write: WorkshopJobWrite) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [form, setForm] = useState<JobDraft | null>(draft);
  const [error, setError] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  if (!form) return null;

  const times = timeOptions(workshopStartTime, workshopEndTime);

  const applyWorkOrder = (wo: PlannerWorkOrder) => {
    setForm({
      ...form,
      workOrderId: wo.id,
      workOrderNumber: wo.external_number,
      amount: wo.amount,
      carDescription: wo.vehicle_description ?? form.carDescription,
      vin: wo.vin ?? form.vin,
      clientName: wo.customer_name ?? form.clientName,
    });
  };

  const save = async () => {
    if (timeToMinutes(form.endTime) <= timeToMinutes(form.startTime)) {
      setError("Окончание должно быть позже начала");
      return;
    }
    try {
      await onSave({
        work_order_id: form.workOrderId,
        car_description: form.carDescription || null,
        vin: form.vin || null,
        plate: form.plate || null,
        client_name: form.clientName || null,
        work_description: form.workDescription || null,
        job_date: form.jobDate,
        post_number: form.postNumber,
        start_time: `${form.startTime}:00`,
        end_time: `${form.endTime}:00`,
        norm_hours: form.normHours || null,
        status_id: form.statusId,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };

  return (
    <>
      <AdminModal open={open} title={form.jobId ? "Запись на пост" : "Новая запись"} onClose={onClose}>
        <WorkOrderAutocomplete
          value={form.workOrderNumber}
          onChange={(text) => setForm({ ...form, workOrderNumber: text, workOrderId: null, amount: null })}
          onSelect={applyWorkOrder}
        />

        <div className="admin-form-grid">
          <div className="admin-form-field">
            <label htmlFor="wj-car">Автомобиль</label>
            <input id="wj-car" value={form.carDescription} onChange={(e) => setForm({ ...form, carDescription: e.target.value })} />
          </div>
          <div className="admin-form-field">
            <label htmlFor="wj-vin">VIN</label>
            <input id="wj-vin" value={form.vin} onChange={(e) => setForm({ ...form, vin: e.target.value })} />
          </div>
          <div className="admin-form-field">
            <label htmlFor="wj-plate">Гос.номер</label>
            <input id="wj-plate" value={form.plate} onChange={(e) => setForm({ ...form, plate: e.target.value })} />
          </div>
          <div className="admin-form-field">
            <label htmlFor="wj-client">Клиент</label>
            <input id="wj-client" value={form.clientName} onChange={(e) => setForm({ ...form, clientName: e.target.value })} />
          </div>
        </div>

        <div className="admin-form-field">
          <label htmlFor="wj-work">Работы</label>
          <textarea
            id="wj-work"
            rows={2}
            value={form.workDescription}
            onChange={(e) => setForm({ ...form, workDescription: e.target.value })}
          />
        </div>

        <div className="admin-form-grid">
          <div className="admin-form-field">
            <label htmlFor="wj-date">Дата</label>
            <input id="wj-date" type="date" value={form.jobDate} onChange={(e) => setForm({ ...form, jobDate: e.target.value })} />
          </div>
          <div className="admin-form-field">
            <label htmlFor="wj-post">Пост</label>
            <select
              id="wj-post"
              value={form.postNumber}
              onChange={(e) => setForm({ ...form, postNumber: Number(e.target.value) })}
            >
              {Array.from({ length: postsCount }, (_, i) => i + 1).map((post) => (
                <option key={post} value={post}>
                  Пост {post}
                </option>
              ))}
            </select>
          </div>
          <div className="admin-form-field">
            <label htmlFor="wj-start">Начало</label>
            <input
              id="wj-start"
              list="wj-time-options"
              value={form.startTime}
              onChange={(e) => setForm({ ...form, startTime: e.target.value })}
            />
          </div>
          <div className="admin-form-field">
            <label htmlFor="wj-end">Окончание</label>
            <input
              id="wj-end"
              list="wj-time-options"
              value={form.endTime}
              onChange={(e) => setForm({ ...form, endTime: e.target.value })}
            />
          </div>
          <datalist id="wj-time-options">
            {times.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>

          <div className="admin-form-field">
            <label htmlFor="wj-nh">Норма-часы</label>
            <input
              id="wj-nh"
              type="number"
              step="0.1"
              min="0"
              value={form.normHours}
              onChange={(e) => setForm({ ...form, normHours: e.target.value })}
            />
          </div>
          <div className="admin-form-field">
            <label htmlFor="wj-amount">Сумма</label>
            <input id="wj-amount" value={form.amount ?? ""} readOnly placeholder="—" />
          </div>
          <div className="admin-form-field">
            <label htmlFor="wj-status">Статус</label>
            <select id="wj-status" value={form.statusId ?? ""} onChange={(e) => setForm({ ...form, statusId: e.target.value || null })}>
              <option value="">—</option>
              {statuses.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {error && <p className="admin-form-error">{error}</p>}
        <div className="admin-form-actions">
          {form.jobId && (
            <button type="button" className="admin-btn admin-btn-danger" onClick={() => setConfirmingDelete(true)}>
              Удалить
            </button>
          )}
          <span className="admin-form-actions-spacer" />
          <button type="button" className="admin-btn" onClick={onClose}>
            Отмена
          </button>
          <button type="button" className="admin-btn admin-btn-primary" onClick={save}>
            Сохранить
          </button>
        </div>
      </AdminModal>

      <AdminModal open={confirmingDelete} title="Удалить запись?" onClose={() => setConfirmingDelete(false)}>
        <p>Точно хотите удалить запись? Данные восстановить будет невозможно.</p>
        <div className="admin-form-actions">
          <span className="admin-form-actions-spacer" />
          <button type="button" className="admin-btn" onClick={() => setConfirmingDelete(false)}>
            Отмена
          </button>
          <button
            type="button"
            className="admin-btn admin-btn-danger"
            onClick={async () => {
              await onDelete();
              // onDelete already closes the main edit dialog via its own
              // state, but this confirm dialog is a second, independent
              // <AdminModal> with its own open/close state - without
              // resetting it too, it stayed open (visibly stuck) after a
              // successful delete.
              setConfirmingDelete(false);
            }}
          >
            Удалить
          </button>
        </div>
      </AdminModal>
    </>
  );
}

export function jobToDraft(job: WorkshopJob): JobDraft {
  return {
    jobId: job.id,
    workOrderId: job.work_order_id,
    workOrderNumber: job.work_order_number ?? "",
    amount: job.amount,
    carDescription: job.car_description ?? "",
    vin: job.vin ?? "",
    plate: job.plate ?? "",
    clientName: job.client_name ?? "",
    workDescription: job.work_description ?? "",
    jobDate: job.job_date,
    postNumber: job.post_number,
    startTime: job.start_time.slice(0, 5),
    endTime: job.end_time.slice(0, 5),
    normHours: job.norm_hours ?? "",
    statusId: job.status_id,
  };
}

export function emptyJobDraft(jobDate: string, postNumber: number, startTime: string, endTime: string): JobDraft {
  return {
    jobId: null,
    workOrderId: null,
    workOrderNumber: "",
    amount: null,
    carDescription: "",
    vin: "",
    plate: "",
    clientName: "",
    workDescription: "",
    jobDate,
    postNumber,
    startTime,
    endTime,
    normHours: "",
    statusId: null,
  };
}
