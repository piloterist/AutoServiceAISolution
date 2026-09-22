"use client";

import { useState } from "react";

import { DateInput } from "@/components/DateInput";
import { AdminModal } from "@/components/settings/AdminModal";
import type { PlannerWorkOrder, SlesarkaStatus, WorkshopJob, WorkshopJobWrite } from "@/lib/backend-api";
import { lookupWorkOrderByPlate } from "@/lib/planner-client";
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

function durationHours(startTime: string, endTime: string): string {
  const minutes = timeToMinutes(endTime) - timeToMinutes(startTime);
  if (minutes <= 0) return "0";
  const hours = minutes / 60;
  return Number.isInteger(hours) ? String(hours) : hours.toFixed(1);
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
  fivesystemsApiEnabled,
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
  /** Настройки → Интеграции → "Включить API" - "Получить ЗН" stays
   * disabled regardless of the Гос.номер field when this is off. */
  fivesystemsApiEnabled: boolean;
  onClose: () => void;
  onSave: (write: WorkshopJobWrite) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [form, setForm] = useState<JobDraft | null>(draft);
  const [error, setError] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [plateLookupBusy, setPlateLookupBusy] = useState(false);
  const [plateLookupError, setPlateLookupError] = useState<string | null>(null);

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

  // Fallback for today's own ЗН - the 1C export is now once a day (see
  // DEPLOYMENT.md), so a car that just arrived genuinely won't be found by
  // the usual "Заказ-наряд" autocomplete above yet. Uses the Гос.номер
  // field already on this card (no separate input) - lives here, not in
  // WorkOrderAutocomplete, precisely because it reads that field.
  const lookupByPlate = async () => {
    if (!fivesystemsApiEnabled || !form.plate.trim()) return;
    setPlateLookupBusy(true);
    setPlateLookupError(null);
    try {
      const wo = await lookupWorkOrderByPlate(form.plate.trim());
      applyWorkOrder(wo);
    } catch (err) {
      const message = err instanceof Error ? err.message : "";
      setPlateLookupError(
        message.includes("404")
          ? "Открытый заказ-наряд с таким гос.номером не найден"
          : message.includes("503")
            ? "Поиск по 5Systems сейчас отключён"
            : "Не удалось получить данные — попробуйте ещё раз или введите вручную",
      );
    } finally {
      setPlateLookupBusy(false);
    }
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
            <button
              type="button"
              className="admin-btn planner-plate-lookup-btn"
              disabled={!fivesystemsApiEnabled || !form.plate.trim() || plateLookupBusy}
              onClick={lookupByPlate}
            >
              {plateLookupBusy ? "Ищем…" : "Получить ЗН"}
            </button>
            {plateLookupError && <p className="admin-form-error planner-plate-lookup-error">{plateLookupError}</p>}
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
            <DateInput id="wj-date" value={form.jobDate} onChange={(iso) => setForm({ ...form, jobDate: iso })} />
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
            {/* A <select>, not <input list=...>+<datalist>: a datalist's
                suggestions narrow to whatever already matches the typed
                value, so once the field had a time in it the dropdown
                only ever showed that one entry back - useless for
                browsing the other slots. */}
            <select id="wj-start" value={form.startTime} onChange={(e) => setForm({ ...form, startTime: e.target.value })}>
              {(times.includes(form.startTime) ? times : [form.startTime, ...times]).map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div className="admin-form-field">
            <label htmlFor="wj-end">Окончание</label>
            <select id="wj-end" value={form.endTime} onChange={(e) => setForm({ ...form, endTime: e.target.value })}>
              {(times.includes(form.endTime) ? times : [form.endTime, ...times]).map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="admin-form-field">
            <label htmlFor="wj-duration">Длительность ч.</label>
            <input id="wj-duration" readOnly value={durationHours(form.startTime, form.endTime)} />
          </div>
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
              try {
                await onDelete();
                // onDelete already closes the main edit dialog via its own
                // state, but this confirm dialog is a second, independent
                // <AdminModal> with its own open/close state - without
                // resetting it too, it stayed open (visibly stuck) after a
                // successful delete.
                setConfirmingDelete(false);
              } catch (err) {
                // A failed delete (backend rejects it, network hiccup, ...)
                // must still close this confirm dialog - otherwise it's
                // stuck the same way, just via a different path - and
                // surface why, reusing the main dialog's own error banner.
                setError(err instanceof Error ? err.message : "Не удалось удалить");
                setConfirmingDelete(false);
              }
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

export function emptyJobDraft(
  jobDate: string,
  postNumber: number,
  startTime: string,
  endTime: string,
  statuses: SlesarkaStatus[],
): JobDraft {
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
    // New records start in "Запись" - there is no blank/dash option any
    // more (see the status <select> above), so a new job must always get
    // a real status from the moment it's created.
    statusId: statuses.find((s) => s.name === "Запись")?.id ?? statuses[0]?.id ?? null,
  };
}
