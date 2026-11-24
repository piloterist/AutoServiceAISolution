"use client";

import Link from "next/link";
import { useState } from "react";

import { DateInput } from "@/components/DateInput";
import { AdminModal } from "@/components/settings/AdminModal";
import type { BodyCar, BodyCarWrite, Employee, PlannerWorkOrder } from "@/lib/backend-api";
import { lookupWorkOrderByPlate } from "@/lib/planner-client";
import { BODY_STAGE_TYPES, CAR_STATUSES } from "@/lib/planner-constants";
import { addDaysIso, diffDaysIso, formatShortDate, todayIso } from "@/lib/planner-time";

import { WorkOrderAutocomplete } from "./WorkOrderAutocomplete";

type StageDraft = {
  stageName: string;
  note: string;
  startDate: string;
  endDate: string;
  employeeId: string;
  /** Этап перетащен на новое место в этой сессии редактирования: пока форма открыта, его даты
   * сдвигают следующие этапы (иначе правку дат пришлось бы повторять руками у каждого). */
  moved?: boolean;
};

export type CarDraft = {
  carId: string | null;
  workOrderId: string | null;
  workOrderNumber: string;
  carDescription: string;
  vin: string;
  plate: string;
  clientName: string;
  phone: string;
  workDescription: string;
  status: string;
  onSite: boolean;
  stages: StageDraft[];
  // Read-only, set only for an existing record - see carToDraft/
  // emptyCarDraft below and WorkshopJobDialog's same field for why.
  // "Создан" (createdAt) added 2026-10-04.
  createdAt: string | null;
  createdByName: string | null;
};

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Restores "each stage must start no earlier than the previous one starts"
 * (product brief: даты этапов могут совпадать/пересекаться, но не быть
 * раньше даты начала предыдущего этапа - see BodyView.tsx's merged-segment
 * rendering for coinciding/overlapping stages) by shifting a violating
 * stage - and, by the same delta, every stage after it - forward just
 * enough to close the gap. Preserves each stage's own duration rather than
 * clamping/shrinking it. Used after row removal and after editing a
 * stage's own end date (editing a start goes through updateStageStart
 * below, which cascades directly). */
function fixupStageOrder(stages: StageDraft[]): StageDraft[] {
  const fixed = [...stages];
  let prevStart: string | null = null;
  for (let i = 0; i < fixed.length; i++) {
    if (!fixed[i].startDate) continue; // этап без дат (его только что перетащили) в порядке не участвует
    if (prevStart && fixed[i].startDate < prevStart) {
      const delta = diffDaysIso(fixed[i].startDate, prevStart);
      for (let j = i; j < fixed.length; j++) {
        if (fixed[j].startDate) fixed[j] = shiftStage(fixed[j], delta);
      }
    }
    prevStart = fixed[i].startDate;
  }
  return fixed;
}

function shiftStage(stage: StageDraft, delta: number): StageDraft {
  return { ...stage, startDate: addDaysIso(stage.startDate, delta), endDate: addDaysIso(stage.endDate, delta) };
}

/** Начало ближайшего предыдущего этапа с датами (этапы без дат пропускаются). */
function previousStart(stages: StageDraft[], index: number): string | null {
  for (let i = index - 1; i >= 0; i--) {
    if (stages[i].startDate) return stages[i].startDate;
  }
  return null;
}

/** Перенос этапа: он встаёт на новое место БЕЗ дат (их укажут заново), а те, что шли после
 * его прежнего места, сдвигаются назад - следующий этап начинается там, где начинался
 * вынутый, так что дыры в плане не остаётся. */
function moveStageRow(stages: StageDraft[], from: number, to: number): StageDraft[] {
  const rest = [...stages];
  const [moved] = rest.splice(from, 1);
  if (moved.startDate) {
    const next = rest.slice(from).find((s) => s.startDate);
    const delta = next ? diffDaysIso(next.startDate, moved.startDate) : 0;
    if (delta < 0) {
      for (let j = from; j < rest.length; j++) {
        if (rest[j].startDate) rest[j] = shiftStage(rest[j], delta);
      }
    }
  }
  rest.splice(to, 0, { ...moved, startDate: "", endDate: "", moved: true });
  return rest;
}

/** Для перетащенного этапа: следующие за ним этапы сдвигаются так, чтобы ближайший начинался
 * на следующий день после его конца (как у нового этапа). Остальные этапы между собой не
 * трогаем - пересечения этапов по-прежнему разрешены. */
function followMovedStage(stages: StageDraft[], index: number): StageDraft[] {
  const stage = stages[index];
  if (!stage.endDate) return stages;
  const next = stages.find((s, i) => i > index && s.startDate);
  if (!next) return stages;
  const delta = diffDaysIso(next.startDate, addDaysIso(stage.endDate, 1));
  if (delta === 0) return stages;
  return stages.map((s, i) => (i > index && s.startDate ? shiftStage(s, delta) : s));
}

function newStageRow(previous: StageDraft | undefined, fallbackDate: string): StageDraft {
  const start = previous ? addDaysIso(previous.endDate, 1) : fallbackDate;
  return { stageName: BODY_STAGE_TYPES[0], note: "", startDate: start, endDate: start, employeeId: "" };
}

/** Caller must remount with a fresh `key` per draft - see WorkshopJobDialog. */
export function BodyCarDialog({
  open,
  draft,
  employees,
  workshopId,
  fivesystemsApiEnabled,
  onClose,
  onSave,
  onDelete,
}: {
  open: boolean;
  draft: CarDraft | null;
  /** Filtered below by цех (workshopId), not by specialty - see the
   * "Сотрудник" <select> in each stage row. */
  employees: Employee[];
  workshopId: string;
  /** Настройки → Интеграции → "Включить API" - "Получить ЗН" stays
   * disabled regardless of the Гос.номер field when this is off. */
  fivesystemsApiEnabled: boolean;
  onClose: () => void;
  onSave: (write: BodyCarWrite) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [form, setForm] = useState<CarDraft | null>(draft);
  const [error, setError] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [plateLookupBusy, setPlateLookupBusy] = useState(false);
  const [plateLookupError, setPlateLookupError] = useState<string | null>(null);
  const [dragStage, setDragStage] = useState<number | null>(null);
  const [overStage, setOverStage] = useState<number | null>(null);

  if (!form) return null;

  // Filtered by цех only - not by specialty (product ask: any employee
  // assigned to this цех can be picked for any этап).
  const workshopEmployees = employees.filter((e) => e.workshop_id === workshopId);

  const applyWorkOrder = (wo: PlannerWorkOrder) => {
    setForm({
      ...form,
      workOrderId: wo.id,
      workOrderNumber: wo.external_number,
      carDescription: wo.vehicle_description ?? form.carDescription,
      vin: wo.vin ?? form.vin,
      clientName: wo.customer_name ?? form.clientName,
      phone: wo.phone ?? form.phone,
    });
  };

  // Fallback for today's own ЗН - the 1C export is now once a day (see
  // DEPLOYMENT.md), so a car that just arrived genuinely won't be found by
  // the usual "Заказ-наряд" autocomplete above yet. Uses the Гос.номер
  // field already on this card (no separate input).
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

  const updateStage = (index: number, patch: Partial<StageDraft>) => {
    const stages = form.stages.map((s, i) => (i === index ? { ...s, ...patch } : s));
    setForm({ ...form, stages });
  };

  /** Moving any stage's start shifts its own end by the same amount (keeps
   * that stage's own duration) and cascades every later stage by the same
   * delta too, so the whole rest of the plan slides together instead of
   * just overlapping the next stage - for the first stage this is "when
   * does the car arrive"; for a middle one it's the same idea starting
   * from that point on (see the same "start" semantics in BodyView's
   * cap-drag). Clamped so it can't move earlier than the PREVIOUS stage's
   * own start (product ask: coinciding/overlapping dates are fine, going
   * backwards past where the previous stage itself starts is not). */
  const updateStageStart = (index: number, rawStart: string) => {
    if (!rawStart) return;
    const prev = previousStart(form.stages, index);
    const startDate = prev && rawStart < prev ? prev : rawStart;
    const stage = form.stages[index];
    if (!stage.startDate) {
      // Этап без дат (перетащенный): получает дату начала, длительность - один день.
      const stages = form.stages.map((s, i) => (i === index ? { ...s, startDate, endDate: startDate } : s));
      setForm({ ...form, stages: followMovedStage(stages, index) });
      return;
    }
    const delta = diffDaysIso(stage.startDate, startDate);
    if (delta === 0) return;
    const stages = form.stages.map((s, i) => (i < index || !s.startDate ? s : shiftStage(s, delta)));
    setForm({ ...form, stages });
  };

  const updateStageEnd = (index: number, rawEnd: string) => {
    if (!rawEnd) return;
    const stage = form.stages[index];
    if (!stage.startDate) {
      const prev = previousStart(form.stages, index);
      const date = prev && rawEnd < prev ? prev : rawEnd;
      const stages = form.stages.map((s, i) => (i === index ? { ...s, startDate: date, endDate: date } : s));
      setForm({ ...form, stages: followMovedStage(stages, index) });
      return;
    }
    const endDate = rawEnd < stage.startDate ? stage.startDate : rawEnd;
    const stages = form.stages.map((s, i) => (i === index ? { ...s, endDate } : s));
    setForm({ ...form, stages: stage.moved ? followMovedStage(stages, index) : fixupStageOrder(stages) });
  };

  const addStage = () => {
    const lastDated = [...form.stages].reverse().find((s) => s.endDate);
    setForm({ ...form, stages: [...form.stages, newStageRow(lastDated, todayIso())] });
  };

  const removeStage = (index: number) => {
    const remaining = form.stages.filter((_, i) => i !== index);
    setForm({ ...form, stages: fixupStageOrder(remaining) });
  };

  const moveStage = (from: number, to: number) => {
    if (from === to || from < 0 || to < 0 || to >= form.stages.length) return;
    setForm({ ...form, stages: moveStageRow(form.stages, from, to) });
  };

  const datedStages = form.stages.filter((s) => s.startDate && s.endDate);
  const span = datedStages.length
    ? {
        start: datedStages.reduce((min, s) => (s.startDate < min ? s.startDate : min), datedStages[0].startDate),
        end: datedStages.reduce((max, s) => (s.endDate > max ? s.endDate : max), datedStages[0].endDate),
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
        phone: form.phone || null,
        work_description: form.workDescription || null,
        status: form.status,
        on_site: form.onSite,
        stages: form.stages.map((s) => ({
          stage_name: s.stageName,
          note: s.note || null,
          start_date: s.startDate,
          end_date: s.endDate,
          employee_id: s.employeeId || null,
        })),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    }
  };

  return (
    <>
      <AdminModal
        open={open}
        title={form.carId ? "Карточка автомобиля" : "Новая машина в кузовном цехе"}
        onClose={onClose}
        wide
        headerActions={
          form.workOrderId && (
            <Link href={`/work-orders/${form.workOrderId}`} className="admin-btn" onClick={(e) => e.stopPropagation()}>
              Перейти к ЗН
            </Link>
          )
        }
      >
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
            <label htmlFor="bc-client">Клиент</label>
            <input id="bc-client" value={form.clientName} onChange={(e) => setForm({ ...form, clientName: e.target.value })} />
          </div>
          <div className="admin-form-field">
            <label htmlFor="bc-phone">Телефон</label>
            <input id="bc-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          </div>
          <div className="admin-form-field">
            <label htmlFor="bc-status">Статус</label>
            <select id="bc-status" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              {CAR_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
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

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={form.onSite}
            onChange={(e) => setForm({ ...form, onSite: e.target.checked })}
          />
          На территории
        </label>

        <fieldset className="planner-stage-fieldset">
          <legend>Этапы работ</legend>
          <div className="planner-stage-header">
            <span />
            <span>Этап</span>
            <span>Сотрудник</span>
            <span>Заметка</span>
            <span>С</span>
            <span>По</span>
            <span />
          </div>
          {form.stages.map((stage, index) => (
            <div
              className={[
                "planner-stage-row",
                dragStage === index ? "planner-stage-row--dragging" : "",
                dragStage !== null && overStage === index && dragStage !== index ? "planner-stage-row--over" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              key={index}
              onDragOver={(event) => {
                if (dragStage === null) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
                if (overStage !== index) setOverStage(index);
              }}
              onDrop={(event) => {
                if (dragStage === null) return;
                event.preventDefault();
                moveStage(dragStage, index);
                setDragStage(null);
                setOverStage(null);
              }}
            >
              <span
                className="planner-stage-handle"
                draggable
                title="Перетащить этап (даты нужно будет указать заново)"
                aria-label="Перетащить этап"
                onDragStart={(event) => {
                  event.dataTransfer.effectAllowed = "move";
                  event.dataTransfer.setData("text/plain", String(index));
                  const row = event.currentTarget.closest(".planner-stage-row");
                  if (row) event.dataTransfer.setDragImage(row, 10, 10);
                  // Не менять DOM строки внутри dragstart: Chrome в этом случае может сразу отменить перетаскивание.
                  window.setTimeout(() => setDragStage(index), 0);
                }}
                onDragEnd={() => {
                  setDragStage(null);
                  setOverStage(null);
                }}
              >
                ☰
              </span>
              <select value={stage.stageName} onChange={(e) => updateStage(index, { stageName: e.target.value })}>
                {BODY_STAGE_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
              <select value={stage.employeeId} onChange={(e) => updateStage(index, { employeeId: e.target.value })}>
                <option value="">—</option>
                {workshopEmployees.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.full_name}
                  </option>
                ))}
              </select>
              <input value={stage.note} placeholder="заметка" onChange={(e) => updateStage(index, { note: e.target.value })} />
              <DateInput value={stage.startDate} onChange={(iso) => updateStageStart(index, iso)} />
              <DateInput value={stage.endDate} onChange={(iso) => updateStageEnd(index, iso)} />
              {index > 0 || !stage.startDate ? (
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

        {form.carId && (
          <div className="admin-form-meta">
            <span>RecId: {form.carId}</span>
            <span>Создан: {form.createdAt ? formatDateTime(form.createdAt) : "—"}</span>
            <span>Создал: {form.createdByName ?? "—"}</span>
          </div>
        )}

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
    phone: car.phone ?? "",
    workDescription: car.work_description ?? "",
    status: car.status,
    onSite: car.on_site,
    stages: car.stages.map((s) => ({
      stageName: s.stage_name,
      note: s.note ?? "",
      startDate: s.start_date,
      endDate: s.end_date,
      employeeId: s.employee_id ?? "",
    })),
    createdAt: car.created_at,
    createdByName: car.created_by_name,
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
    phone: "",
    workDescription: "",
    status: "К приёмке",
    onSite: false,
    stages: [newStageRow(undefined, arriveDate)],
    createdAt: null,
    createdByName: null,
  };
}
