"use client";

import { useState } from "react";

import { employeesOfWorkshop, workshopLabel } from "@/components/crm/WorkshopsContext";
import { formatPhone } from "@/components/crm/columns";
import { DateInput } from "@/components/DateInput";
import { AdminModal } from "@/components/settings/AdminModal";
import type { CrmTask, Employee, Workshop } from "@/lib/backend-api";

export type ManualTaskResult = { task: CrmTask; created: boolean; linked: "call" | "lead" | null };

/** «Создать» на доске задач: карточка, заполненная руками. Обязательны телефон и цех; цех и
 * сотрудник по умолчанию - текущего пользователя. Ниже - комментарий и запланированное действие
 * (как в окне карточки), необязательные. Сервер ищет телефон в телефонии и среди заявок с сайта и
 * связывает карточку с найденным звонком / заявкой; если телефон уже ведётся - откроется существующая
 * карточка. */
export function ManualTaskDialog({
  open,
  workshops,
  employees,
  defaultWorkshopId,
  defaultEmployeeId,
  onClose,
  onDone,
}: {
  open: boolean;
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
  const [clientName, setClientName] = useState("");
  const [commentOpen, setCommentOpen] = useState(false);
  const [actionOpen, setActionOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [actionDate, setActionDate] = useState("");
  const [actionComment, setActionComment] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      setActionOpen(true);
      setError("Укажите комментарий к запланированному действию");
      return;
    }
    if (actionComment.trim() && !actionDate) {
      setActionOpen(true);
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
          client_name: clientName || null,
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
    <AdminModal open={open} title="Новая задача" onClose={() => !saving && onClose()}>
      <div className="call-control-dialog">
        <label htmlFor="manual-task-phone">Телефон *</label>
        <input
          id="manual-task-phone"
          type="tel"
          inputMode="tel"
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
          onBlur={() => digits.length >= 10 && setPhone(formatPhone(digits.slice(-10)))}
          placeholder="+7 900 123-45-67"
          autoFocus
        />
        <label htmlFor="manual-task-client">Клиент</label>
        <input
          id="manual-task-client"
          value={clientName}
          onChange={(event) => setClientName(event.target.value)}
          placeholder="Имя клиента (необязательно)"
        />
        <label htmlFor="manual-task-workshop">Цех *</label>
        <select
          id="manual-task-workshop"
          value={workshopId}
          onChange={(event) => {
            const next = event.target.value;
            setWorkshopId(next);
            // Сотрудник остаётся, только если он работает в новом цехе (или без цеха в справочнике).
            const stays = employeesOfWorkshop(employees, next || null).some((e) => e.id === employeeId);
            if (!stays && !(own && own.id === employeeId && !own.workshop_id)) setEmployeeId("");
          }}
        >
          <option value="">Выберите цех…</option>
          {workshops.map((workshop) => (
            <option key={workshop.id} value={workshop.id}>
              {workshopLabel(workshop)}
            </option>
          ))}
        </select>
        <label htmlFor="manual-task-employee">Сотрудник</label>
        <select
          id="manual-task-employee"
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

        <button
          type="button"
          className="task-detail-toggle"
          aria-expanded={commentOpen}
          onClick={() => setCommentOpen((prev) => !prev)}
        >
          {commentOpen ? "▾" : "▸"} Комментарий{comment.trim() ? " ✓" : ""}
        </button>
        {commentOpen && (
          <div className="task-detail-comment-form">
            <textarea
              rows={3}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="Комментарий к задаче"
              aria-label="Комментарий"
            />
          </div>
        )}

        <button
          type="button"
          className="task-detail-toggle"
          aria-expanded={actionOpen}
          onClick={() => setActionOpen((prev) => !prev)}
        >
          {actionOpen ? "▾" : "▸"} Действие{actionDate ? " ✓" : ""}
        </button>
        {actionOpen && (
          <div className="task-detail-comment-form">
            <div className="task-detail-plan">
              <label htmlFor="manual-task-date">Дата контакта</label>
              <DateInput id="manual-task-date" value={actionDate} onChange={setActionDate} />
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
          Телефон будет проверен в телефонии и среди заявок с сайта: найденный звонок или заявка свяжутся с задачей.
        </p>
        {error && <p className="admin-form-error">{error}</p>}
        <div className="request-control-actions">
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
        </div>
      </div>
    </AdminModal>
  );
}
