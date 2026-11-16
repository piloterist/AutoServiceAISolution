"use client";

import { useState } from "react";

import {
  employeesOfWorkshop,
  phoneKey,
  useControlTasks,
  useEmployees,
  useWorkshops,
  workshopLabel,
} from "@/components/crm/WorkshopsContext";
import { AdminModal } from "@/components/settings/AdminModal";
import type { CrmTask, CrmTaskStatus } from "@/lib/backend-api";

type State = "idle" | "saving" | "added" | "already";

const COLUMN_TITLES: Record<CrmTaskStatus, string> = {
  control: "На контроле",
  inspection: "Записан на осмотр",
  thinking: "Думает",
  refused: "Отказ",
  work_order: "Заказ-наряд",
};

/** «На контроль» у звонка (product ask, 2026-11-15) - правее кнопки play. Открывает диалог с выбором
 * цеха (если звонок привязан к цеху, он уже выбран); без цеха на контроль не взять. После
 * подтверждения на «Доске задач» CRM появляется карточка в столбце «На контроле». Если этот телефон
 * уже ведётся, новая карточка не создаётся - кнопка так и говорит. */
export function PutOnControlButton({
  callId,
  client,
  callWorkshopId,
}: {
  callId: string;
  /** The caller's phone: if a card for it is already in work, the button shows its column. */
  client?: string | null;
  /** The цех the call was routed to (telephony settings), preselected in the dialog. */
  callWorkshopId?: string | null;
}) {
  const workshops = useWorkshops();
  const { employees, currentEmployeeId } = useEmployees();
  const [employeeId, setEmployeeId] = useState("");
  const [state, setState] = useState<State>("idle");
  const [open, setOpen] = useState(false);
  const [workshopId, setWorkshopId] = useState("");
  const [error, setError] = useState<string | null>(null);
  // The column the card landed in: not «На контроле» if the planner / a request / a work order
  // already exists after the call.
  const [column, setColumn] = useState<CrmTaskStatus>("control");

  const { byPhone, register, show } = useControlTasks();
  const existing = byPhone[phoneKey(client)] ?? null;

  // The цех's employees, plus the user's own one when the directory has no цех for them (such an
  // employee fits any цех) - otherwise they would be missing from the list.
  const ownEmployee = employees.find((e) => e.id === currentEmployeeId) ?? null;
  const employeeOptions = employeesOfWorkshop(employees, workshopId || null);
  if (ownEmployee && !ownEmployee.workshop_id && !employeeOptions.some((e) => e.id === ownEmployee.id)) {
    employeeOptions.unshift(ownEmployee);
  }

  // Preselect the user's own employee when they work in the chosen цех; otherwise nobody.
  const preselectEmployee = (forWorkshop: string) =>
    currentEmployeeId &&
    (employeesOfWorkshop(employees, forWorkshop).some((e) => e.id === currentEmployeeId) ||
      (ownEmployee !== null && !ownEmployee.workshop_id))
      ? currentEmployeeId
      : "";

  const openDialog = () => {
    let initialWorkshop =
      callWorkshopId && workshops.some((w) => w.id === callWorkshopId) ? callWorkshopId : "";
    // A call without a цех: take the цех of the user's own employee, so the form fills itself.
    if (!initialWorkshop && currentEmployeeId) {
      const own = employees.find((e) => e.id === currentEmployeeId);
      if (own?.workshop_id && workshops.some((w) => w.id === own.workshop_id)) initialWorkshop = own.workshop_id;
    }
    setWorkshopId(initialWorkshop);
    setEmployeeId(initialWorkshop ? preselectEmployee(initialWorkshop) : "");
    setError(null);
    setOpen(true);
  };

  const submit = async () => {
    if (!workshopId) {
      setError("Выберите цех");
      return;
    }
    setState("saving");
    setError(null);
    try {
      const res = await fetch("/api/crm-tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ call_id: callId, workshop_id: workshopId, employee_id: employeeId || null }),
      });
      const body = (await res.json()) as { task?: CrmTask; created?: boolean; error?: string };
      if (!res.ok || !body.task) throw new Error(body.error ?? "Не удалось взять на контроль");
      setColumn(body.task.status);
      register(body.task);
      setState(body.created ? "added" : "already");
      setOpen(false);
    } catch (err) {
      setState("idle");
      setError(err instanceof Error ? err.message : "Не удалось взять на контроль");
    }
  };

  // The phone is already on the board: the button is the card's column (same colour as there).
  if (existing) {
    return (
      <button
        type="button"
        className={`call-control-status task-column--${existing.status}`}
        title={`На «Доске задач», столбец «${COLUMN_TITLES[existing.status]}» - открыть задачу на доске`}
        onClick={(event) => {
          event.stopPropagation();
          show(existing);
        }}
      >
        {COLUMN_TITLES[existing.status]}
      </button>
    );
  }

  return (
    <>
      <button
        type="button"
        className="call-control-btn"
        onClick={(event) => {
          event.stopPropagation();
          openDialog();
        }}
        title="Взять телефон на контроль («Доска задач»)"
      >
        На контроль
      </button>

      <AdminModal
        open={open}
        title="Взять на контроль"
        onClose={() => {
          if (state !== "saving") setOpen(false);
        }}
      >
        <div className="call-control-dialog" onClick={(event) => event.stopPropagation()}>
          <label htmlFor={`call-control-workshop-${callId}`}>Цех</label>
          <select
            id={`call-control-workshop-${callId}`}
            value={workshopId}
            onChange={(event) => {
              setWorkshopId(event.target.value);
              // The employee list follows the цех; the user's own employee is picked if they work there.
              setEmployeeId(event.target.value ? preselectEmployee(event.target.value) : "");
            }}
          >
            <option value="">Выберите цех…</option>
            {workshops.map((workshop) => (
              <option key={workshop.id} value={workshop.id}>
                {workshopLabel(workshop)}
              </option>
            ))}
          </select>
          <label htmlFor={`call-control-employee-${callId}`}>Сотрудник</label>
          <select
            id={`call-control-employee-${callId}`}
            value={employeeId}
            disabled={!workshopId}
            onChange={(event) => setEmployeeId(event.target.value)}
          >
            <option value="">{workshopId ? "Не выбран" : "Сначала выберите цех"}</option>
            {employeeOptions.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employee.full_name}
                {employee.specialty ? ` — ${employee.specialty}` : ""}
              </option>
            ))}
          </select>
          {error && <p className="admin-form-error">{error}</p>}
          <div className="request-control-actions">
            <button
              type="button"
              className="admin-btn admin-btn-primary"
              disabled={state === "saving" || !workshopId}
              onClick={() => void submit()}
            >
              {state === "saving" ? "Сохраняем…" : "На контроль"}
            </button>
            <button type="button" className="admin-btn" disabled={state === "saving"} onClick={() => setOpen(false)}>
              Отмена
            </button>
          </div>
        </div>
      </AdminModal>
    </>
  );
}
