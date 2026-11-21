"use client";

import { useState } from "react";

import { columnOf, formatPhone } from "@/components/crm/columns";
import { employeesOfWorkshop, workshopLabel } from "@/components/crm/WorkshopsContext";
import { DateInput } from "@/components/DateInput";
import { AdminModal } from "@/components/settings/AdminModal";
import type { CrmTask, Employee, Workshop } from "@/lib/backend-api";

export type ManualTaskResult = { task: CrmTask; created: boolean; linked: "call" | "lead" | null };

/** «Создать» на доске задач: та же форма, что у окна задачи (TaskDetailModal), только телефон
 * вводится руками (поле выше) и поля «Сотрудник» / «Цех» сразу доступны. Цех и сотрудник по
 * умолчанию - текущего пользователя. Комментарий и запланированное действие необязательны и
 * сохраняются вместе с задачей. Сервер ищет телефон в телефонии и среди заявок с сайта и связывает
 * задачу с найденным звонком / заявкой; если телефон уже ведётся - откроется существующая задача. */
export function ManualTaskDialog({
  workshops,
  employees,
  defaultWorkshopId,
  defaultEmployeeId,
  onClose,
  onDone,
}: {
  workshops: Workshop[];
  employees: Employee[];
  defaultWorkshopId: string;
  defaultEmployeeId: string;
  onClose: () => void;
  onDone: (result: ManualTaskResult) => void;
}) {
  const [phone, setPhone] = useState("");
  const [workshopId, setWorkshopId] = useState(defaultWorkshopId);
  const [employeeId, setEmployeeId] = useState(defaultEmployeeId);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [actionDate, setActionDate] = useState("");
  const [actionComment, setActionComment] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stage = columnOf("control");
  const employeeOptions = employeesOfWorkshop(employees, workshopId || null);
  // Свой сотрудник без цеха в справочнике подходит к любому цеху - не теряем его в списке.
  const own = employees.find((e) => e.id === defaultEmployeeId) ?? null;
  if (own && !own.workshop_id && !employeeOptions.some((e) => e.id === own.id)) employeeOptions.unshift(own);

  const digits = phone.replace(/\D/g, "");

  const submit = async () => {
    if (digits.length < 10) {
      setError(digits ? "Телефон должен содержать не меньше 10 цифр" : "Укажите телефон");
      return;
    }
    if (!workshopId) {
      setError("Выберите цех");
      return;
    }
    if (actionDate && !actionComment.trim()) {
      setActionsOpen(true);
      setError("Укажите комментарий к запланированному действию");
      return;
    }
    if (actionComment.trim() && !actionDate) {
      setActionsOpen(true);
      setError("Укажите дату запланированного действия");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await fetch("/api/crm-tasks/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone,
          workshop_id: workshopId,
          employee_id: employeeId || null,
          comment: comment || null,
          action_date: actionDate || null,
          action_comment: actionComment || null,
        }),
      });
      const body = (await res.json()) as Partial<ManualTaskResult> & { error?: string };
      if (!res.ok || !body.task) throw new Error(body.error ?? "Не удалось создать задачу");
      onDone(body as ManualTaskResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать задачу");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AdminModal
      open
      wide
      title={
        <>
          Лид · новая задача
          <span className={`task-detail-stage task-column--control`}>
            <span aria-hidden="true">{stage.icon}</span> {stage.title}
          </span>
        </>
      }
      onClose={() => !saving && onClose()}
    >
      <div className="task-detail task-column--control">
        <div className="task-detail-summary">
          <div className="task-detail-top">
            <div className="task-detail-main">
              <div className="task-detail-grid">
                <div className="task-detail-row">
                  <label className="task-detail-label" htmlFor="manual-task-phone">
                    Телефон *
                  </label>
                  <input
                    id="manual-task-phone"
                    className="task-detail-select"
                    type="tel"
                    inputMode="tel"
                    value={phone}
                    onChange={(event) => setPhone(event.target.value)}
                    onBlur={() => digits.length >= 10 && setPhone(formatPhone(digits.slice(-10)))}
                    placeholder="+7 900 123-45-67"
                    autoFocus
                  />
                </div>
                <div className="task-detail-row">
                  <span className="task-detail-label">Сотрудник</span>
                  <select
                    className="task-detail-select"
                    value={employeeId}
                    onChange={(event) => setEmployeeId(event.target.value)}
                    aria-label="Сотрудник"
                  >
                    <option value="">Не выбран</option>
                    {employeeOptions.map((employee) => (
                      <option key={employee.id} value={employee.id}>
                        {employee.full_name}
                        {employee.specialty ? ` — ${employee.specialty}` : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="task-detail-row">
                  <span className="task-detail-label">Цех *</span>
                  <select
                    className="task-detail-select"
                    value={workshopId}
                    onChange={(event) => {
                      const next = event.target.value;
                      setWorkshopId(next);
                      // Сотрудник остаётся, только если работает в новом цехе (или цех ему не указан).
                      const keep = employees.find((e) => e.id === employeeId);
                      if (keep?.workshop_id && keep.workshop_id !== next) setEmployeeId("");
                    }}
                    aria-label="Цех"
                  >
                    <option value="">Выберите цех…</option>
                    {workshops.map((workshop) => (
                      <option key={workshop.id} value={workshop.id}>
                        {workshopLabel(workshop)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </div>
            <span className="task-detail-head-actions">
              <span className="task-detail-head-row">
                <button
                  type="button"
                  className="admin-btn admin-btn-primary"
                  disabled={saving || digits.length < 10 || !workshopId}
                  onClick={() => void submit()}
                >
                  {saving ? "Создаём…" : "Создать"}
                </button>
                <button type="button" className="admin-btn" disabled={saving} onClick={onClose}>
                  Отмена
                </button>
              </span>
              {["Запись на осмотр", "Заявка на ремонт", "Заказ-наряд"].map((label) => (
                <button key={label} type="button" className="admin-btn task-detail-navbtn" disabled>
                  {label}
                </button>
              ))}
            </span>
          </div>
          {error && <p className="admin-form-error">{error}</p>}
        </div>

        <button
          type="button"
          className="task-detail-toggle"
          aria-expanded={commentsOpen}
          onClick={() => setCommentsOpen((prev) => !prev)}
        >
          {commentsOpen ? "▾" : "▸"} Комментарии ({comment.trim() ? 1 : 0})
        </button>
        {commentsOpen && (
          <div className="task-detail-comment-form">
            <textarea
              rows={3}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="Написать комментарий…  (сохранится вместе с задачей)"
              aria-label="Комментарий"
            />
          </div>
        )}

        <button
          type="button"
          className="task-detail-toggle"
          aria-expanded={actionsOpen}
          onClick={() => setActionsOpen((prev) => !prev)}
        >
          {actionsOpen ? "▾" : "▸"} Действия ({actionDate && actionComment.trim() ? 1 : 0})
        </button>
        {actionsOpen && (
          <div className="task-detail-comment-form">
            <div className="task-detail-plan">
              <label htmlFor="manual-task-date">Дата контакта</label>
              <DateInput id="manual-task-date" value={actionDate} onChange={setActionDate} />
              <span className="admin-hint">Не запланировано - сроки считаются от создания задачи.</span>
            </div>
            <textarea
              rows={3}
              value={actionComment}
              onChange={(event) => setActionComment(event.target.value)}
              placeholder="Что нужно сделать (комментарий обязателен)"
              aria-label="Комментарий к запланированному действию"
            />
          </div>
        )}

        <p className="admin-hint">
          Телефон проверяется в телефонии и среди заявок с сайта: найденный звонок или заявка связываются с задачей.
        </p>
      </div>
    </AdminModal>
  );
}
