"use client";

import { useState } from "react";

import { AdminModal } from "@/components/settings/AdminModal";
import type { BodyCar, BodyCarWrite, PlannerWorkOrder } from "@/lib/backend-api";
import { BODY_STAGE_TYPES } from "@/lib/planner-constants";
import { addDaysIso, formatShortDate, todayIso } from "@/lib/planner-time";

import { WorkOrderAutocomplete } from "./WorkOrderAutocomplete";

type StageDraft = { stageName: string; note: string; startDate: string; endDate: string };

export type CarDraft = {
  carId: string | null;
  workOrderId: string | null;
  workOrderNumber: string;
  carDescription: string;
  vin: string;
  plate: string;
  clientName: string;
  workDescription: string;
  status: string;
  stages: StageDraft[];
};

/** Restores "later stage's start must not precede an earlier one's" after a
 * row is removed (product brief: "При удалении строки... даты строк позже
 * пересчитываются") - only nudges a stage forward when it would otherwise
 * violate that, doesn't reflow ones that are already fine. */
function fixupStageOrder(stages: StageDraft[]): StageDraft[] {
  const fixed = [...stages];
  for (let i = 1; i < fixed.length; i++) {
    if (fixed[i].startDate < fixed[i - 1].startDate) {
      const newStart = addDaysIso(fixed[i - 1].endDate, 1);
      const shifted = newStart > fixed[i].startDate ? newStart : fixed[i].startDate;
      const newEnd = fixed[i].endDate < shifted ? shifted : fixed[i].endDate;
      fixed[i] = { ...fixed[i], startDate: shifted, endDate: newEnd };
    }
  }
  return fixed;
}

function newStageRow(previous: StageDraft | undefined, fallbackDate: string): StageDraft {
  const start = previous ? addDaysIso(previous.endDate, 1) : fallbackDate;
  return { stageName: BODY_STAGE_TYPES[0], note: "", startDate: start, endDate: start };
}

/** Caller must remount with a fresh `key` per draft - see WorkshopJobDialog. */
export function BodyCarDialog({
  open,
  draft,
  onClose,
  onSave,
  onDelete,
}: {
  open: boolean;
  draft: CarDraft | null;
  onClose: () => void;
  onSave: (write: BodyCarWrite) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [form, setForm] = useState<CarDraft | null>(draft);
  const [error, setError] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  if (!form) return null;

  const applyWorkOrder = (wo: PlannerWorkOrder) => {
    setForm({
      ...form,
      workOrderId: wo.id,
      workOrderNumber: wo.external_number,
      carDescription: wo.vehicle_description ?? form.carDescription,
      vin: wo.vin ?? form.vin,
      clientName: wo.customer_name ?? form.clientName,
    });
  };

  const updateStage = (index: number, patch: Partial<StageDraft>) => {
    const stages = form.stages.map((s, i) => (i === index ? { ...s, ...patch } : s));
    setForm({ ...form, stages });
  };

  const addStage = () => {
    setForm({ ...form, stages: [...form.stages, newStageRow(form.stages[form.stages.length - 1], todayIso())] });
  };

  const removeStage = (index: number) => {
    const remaining = form.stages.filter((_, i) => i !== index);
    setForm({ ...form, stages: fixupStageOrder(remaining) });
  };

  const span = form.stages.length
    ? {
        start: form.stages.reduce((min, s) => (s.startDate < min ? s.startDate : min), form.stages[0].startDate),
        end: form.stages.reduce((max, s) => (s.endDate > max ? s.endDate : max), form.stages[0].endDate),
      }
    : null;

  const save = async () => {
    for (const stage of form.stages) {
      if (!stage.startDate || !stage.endDate) return setError("У каждого этапа должны быть даты «с» и «по»");
      if (stage.endDate < stage.startDate) return setError("Дата «по» этапа раньше даты «с»");
    }
    try {
      await onSave({
        work_order_id: form.workOrderId,
        car_description: form.carDescription || null,
        vin: form.vin || null,
        plate: form.plate || null,
        client_name: form.clientName || null,
        work_description: form.workDescription || null,
        status: form.status,
        stages: form.stages.map((s) => ({
          stage_name: s.stageName,
          note: s.note || null,
          start_date: s.startDate,
          end_date: s.endDate,
        })),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };

  return (
    <>
      <AdminModal open={open} title={form.carId ? "Карточка автомобиля" : "Новая машина в кузовном цехе"} onClose={onClose}>
        <WorkOrderAutocomplete
          value={form.workOrderNumber}
          onChange={(text) => setForm({ ...form, workOrderNumber: text, workOrderId: null })}
          onSelect={applyWorkOrder}
        />

        <div className="admin-form-grid">
          <div className="admin-form-field">
            <label htmlFor="bc-car">Автомобиль</label>
            <input id="bc-car" value={form.carDescription} onChange={(e) => setForm({ ...form, carDescription: e.target.value })} />
          </div>
          <div className="admin-form-field">
            <label htmlFor="bc-vin">VIN</label>
            <input id="bc-vin" value={form.vin} onChange={(e) => setForm({ ...form, vin: e.target.value })} />
          </div>
          <div className="admin-form-field">
            <label htmlFor="bc-plate">Гос.номер</label>
            <input id="bc-plate" value={form.plate} onChange={(e) => setForm({ ...form, plate: e.target.value })} />
          </div>
          <div className="admin-form-field">
            <label htmlFor="bc-client">Клиент</label>
            <input id="bc-client" value={form.clientName} onChange={(e) => setForm({ ...form, clientName: e.target.value })} />
          </div>
        </div>

        <div className="admin-form-field">
          <label htmlFor="bc-work">Работы</label>
          <textarea
            id="bc-work"
            rows={2}
            value={form.workDescription}
            onChange={(e) => setForm({ ...form, workDescription: e.target.value })}
          />
        </div>

        <fieldset className="planner-stage-fieldset">
          <legend>Этапы работ</legend>
          <div className="planner-stage-header">
            <span>Этап</span>
            <span>Заметка</span>
            <span>С</span>
            <span>По</span>
            <span />
          </div>
          {form.stages.map((stage, index) => (
            <div className="planner-stage-row" key={index}>
              <select value={stage.stageName} onChange={(e) => updateStage(index, { stageName: e.target.value })}>
                {BODY_STAGE_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
              <input value={stage.note} placeholder="заметка" onChange={(e) => updateStage(index, { note: e.target.value })} />
              <input type="date" value={stage.startDate} onChange={(e) => updateStage(index, { startDate: e.target.value })} />
              <input type="date" value={stage.endDate} onChange={(e) => updateStage(index, { endDate: e.target.value })} />
              {index > 0 ? (
                <button type="button" className="admin-btn-link admin-btn-link--danger" onClick={() => removeStage(index)}>
                  ×
                </button>
              ) : (
                <span />
              )}
            </div>
          ))}
          <button type="button" className="admin-btn" style={{ marginTop: "0.5rem" }} onClick={addStage}>
            + этап
          </button>
          {span && (
            <p className="planner-stage-span">
              Заезд {formatShortDate(span.start)} - Выезд {formatShortDate(span.end)}
            </p>
          )}
        </fieldset>

        {error && <p className="admin-form-error">{error}</p>}
        <div className="admin-form-actions">
          {form.carId && (
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
                // See the same fix in WorkshopJobDialog.tsx - this confirm
                // dialog is a second, independent <AdminModal>; without
                // resetting its own open state too, it stayed open after a
                // successful delete.
                setConfirmingDelete(false);
              } catch (err) {
                // A failed delete must still close this confirm dialog -
                // otherwise it's stuck the same way, just via a different
                // path - and surface why, reusing the main dialog's error banner.
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

export function carToDraft(car: BodyCar): CarDraft {
  return {
    carId: car.id,
    workOrderId: car.work_order_id,
    workOrderNumber: car.work_order_number ?? "",
    carDescription: car.car_description ?? "",
    vin: car.vin ?? "",
    plate: car.plate ?? "",
    clientName: car.client_name ?? "",
    workDescription: car.work_description ?? "",
    status: car.status,
    stages: car.stages.map((s) => ({ stageName: s.stage_name, note: s.note ?? "", startDate: s.start_date, endDate: s.end_date })),
  };
}

export function emptyCarDraft(arriveDate: string): CarDraft {
  return {
    carId: null,
    workOrderId: null,
    workOrderNumber: "",
    carDescription: "",
    vin: "",
    plate: "",
    clientName: "",
    workDescription: "",
    status: "К приёмке",
    stages: [newStageRow(undefined, arriveDate)],
  };
}
