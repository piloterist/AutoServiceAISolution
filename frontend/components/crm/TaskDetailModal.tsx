"use client";

import { useCallback, useEffect, useState } from "react";

import { DateInput } from "@/components/DateInput";
import { employeesOfWorkshop, useEmployees, useWorkshops, workshopLabel } from "@/components/crm/WorkshopsContext";
import { columnOf, formatDate, formatInspection, formatMoment, formatPhone } from "@/components/crm/columns";
import { AdminModal } from "@/components/settings/AdminModal";
import { CallEventsTable } from "@/components/telephony/TelephonyStatsView";
import type { CrmTask, CrmTaskAction, CrmTaskComment, CrmTaskDetail, LineCallEvent } from "@/lib/backend-api";
import { getClientCallHistoryClient } from "@/lib/telephony-client";

/** Окно лида (product ask, 2026-11-15): клик по карточке доски. Вся информация по телефону -
 * звонки (та же таблица, что на «Звонках»: раскрыть расшифровку, послушать запись), ссылки на
 * заявку на ремонт и заказ-наряд, причина отказа - и комментарии, которые можно оставить на любом
 * этапе, с историей. */
export function TaskDetailModal({
  task,
  onClose,
  onCommentCountChange,
  onChanged,
}: {
  task: CrmTask | null;
  onClose: () => void;
  /** A comment / a planned action was saved - the board reloads (the card's colour may change). */
  onChanged: () => void;
  /** Keeps the card's 💬 counter on the board in step. */
  onCommentCountChange: (taskId: string, count: number) => void;
}) {
  return (
    <AdminModal
      open={task !== null}
      title={
        task ? (
          <>
            Лид · {formatPhone(task.phone)}
            <span className={`task-detail-stage task-column--${task.status}`}>
              <span aria-hidden="true">{columnOf(task.status).icon}</span> {columnOf(task.status).title}
            </span>
          </>
        ) : (
          "Лид"
        )
      }
      onClose={onClose}
      closeOnBackdropClick
      wide
    >
      {task && (
        <TaskDetail
          key={task.id}
          task={task}
          onCommentCountChange={onCommentCountChange}
          onChanged={onChanged}
        />
      )}
    </AdminModal>
  );
}

/** "YYYY-MM-DD HH:MM:SS", Moscow-local - the format of LineCallEvent.time. */
function moscowStamp(iso: string): string {
  return new Date(iso).toLocaleString("sv-SE", { timeZone: "Europe/Moscow" });
}

function TaskDetail({
  task: listedTask,
  onCommentCountChange,
  onChanged,
}: {
  task: CrmTask;
  onCommentCountChange: (taskId: string, count: number) => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<CrmTaskDetail | null>(null);
  // The freshest card (the list's copy goes stale after a planned action is saved).
  const task = detail?.task ?? listedTask;
  const column = columnOf(task.status);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [calls, setCalls] = useState<LineCallEvent[] | null>(null);
  const [callsError, setCallsError] = useState<string | null>(null);

  const [comments, setComments] = useState<CrmTaskComment[]>([]);
  const [actions, setActions] = useState<CrmTaskAction[]>([]);
  const [callsOpen, setCallsOpen] = useState(false);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [text, setText] = useState("");
  const [planText, setPlanText] = useState("");
  // «Запланировать действие»: пусто по умолчанию; с датой комментарий обязателен.
  const [nextDate, setNextDate] = useState("");
  const [saving, setSaving] = useState(false);
  // «Цех» и «Сотрудник» карточки: кнопка «Изменить» открывает выбор, «Сохранить» применяет.
  const workshops = useWorkshops();
  const { employees } = useEmployees();
  const [assigning, setAssigning] = useState(false);
  const [assignWorkshop, setAssignWorkshop] = useState("");
  const [assignEmployee, setAssignEmployee] = useState("");
  const [assignError, setAssignError] = useState<string | null>(null);
  // Редактирование запланированного действия из истории.
  const [editId, setEditId] = useState<string | null>(null);
  const [editDate, setEditDate] = useState("");
  const [editText, setEditText] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [commentError, setCommentError] = useState<string | null>(null);

  const loadDetail = useCallback(async (): Promise<CrmTaskDetail> => {
    const res = await fetch(`/api/crm-tasks/${listedTask.id}`, { cache: "no-store" });
    const body = (await res.json()) as CrmTaskDetail & { error?: string };
    if (!res.ok) throw new Error(body.error ?? "Не удалось загрузить лид");
    setDetail(body);
    setComments(body.comments);
    setActions(body.actions ?? []);
    return body;
  }, [listedTask.id]);

  useEffect(() => {
    loadDetail().catch((err) =>
      setDetailError(err instanceof Error ? err.message : "Не удалось загрузить лид"),
    );
  }, [loadDetail]);

  // Звонки этого телефона начиная со звонка, с которого взяли на контроль: то, что было раньше,
  // - прошлое клиента, а не этот лид.
  useEffect(() => {
    let cancelled = false;
    const since = moscowStamp(task.call_at);
    getClientCallHistoryClient(task.phone)
      .then((result) => {
        if (cancelled) return;
        setCalls(result.events.filter((event) => event.time >= since));
      })
      .catch((err) => {
        if (!cancelled) setCallsError(err instanceof Error ? err.message : "Не удалось загрузить звонки");
      });
    return () => {
      cancelled = true;
    };
  }, [task.phone, task.call_at]);

  // Комментарий; с датой - ещё и запланированное действие (комментарий тогда обязателен).
  const postComment = async (value: string, date: string | null): Promise<boolean> => {
    setSaving(true);
    setCommentError(null);
    try {
      const res = await fetch(`/api/crm-tasks/${task.id}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: value, next_action_date: date }),
      });
      const body = (await res.json()) as CrmTaskComment & { error?: string };
      if (!res.ok) throw new Error(body.error ?? "Не удалось сохранить");
      const fresh = await loadDetail();
      onCommentCountChange(task.id, fresh.comments.length);
      onChanged();
      return true;
    } catch (err) {
      setCommentError(err instanceof Error ? err.message : "Не удалось сохранить");
      return false;
    } finally {
      setSaving(false);
    }
  };

  const addComment = async () => {
    const value = text.trim();
    if (value && (await postComment(value, null))) setText("");
  };

  const addAction = async () => {
    const value = planText.trim();
    if (value && nextDate && (await postComment(value, nextDate))) {
      setPlanText("");
      setNextDate("");
    }
  };

  // The planner opens on the record's цех and day with the record found (as the car search does):
  // the id is matched by the planner's search box, the rest of the records are dimmed.
  const plannerHref =
    task.planner_record_id && task.workshop_id
      ? `/planner?workshop=${task.workshop_id}&zn=${encodeURIComponent(task.planner_record_id)}${
          task.inspection_date ? `&date=${task.inspection_date}` : ""
        }`
      : null;

  const startAssign = () => {
    setAssignWorkshop(task.workshop_id ?? "");
    setAssignEmployee(task.employee_id ?? "");
    setAssignError(null);
    setAssigning(true);
  };

  const saveAssign = async () => {
    setSaving(true);
    setAssignError(null);
    try {
      const res = await fetch(`/api/crm-tasks/${task.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workshop_id: assignWorkshop, employee_id: assignEmployee || null }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error ?? "Не удалось сохранить");
      }
      setAssigning(false);
      await loadDetail();
      onChanged();
    } catch (err) {
      setAssignError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  const saveAction = async () => {
    if (!editId) return;
    setSaving(true);
    setActionError(null);
    try {
      const res = await fetch(`/api/crm-tasks/${task.id}/actions/${editId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ planned_date: editDate, comment: editText }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error ?? "Не удалось сохранить");
      }
      setEditId(null);
      await loadDetail();
      onChanged();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  const removeAction = async (actionId: string) => {
    if (!window.confirm("Удалить запланированное действие?")) return;
    setActionError(null);
    try {
      const res = await fetch(`/api/crm-tasks/${task.id}/actions/${actionId}`, { method: "DELETE" });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error ?? "Не удалось удалить");
      }
      if (editId === actionId) setEditId(null);
      await loadDetail();
      onChanged();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  const numberRow = (label: string, number: string | null) =>
    number && (
      <div className="task-detail-row">
        <span className="task-detail-label">{label}</span>
        <span>{number}</span>
      </div>
    );

  // Кнопка-ссылка в той же вкладке; пока ссылки нет - серая и недоступная.
  const navButton = (label: string, href: string | null, hint: string) =>
    href ? (
      <a href={href} className="admin-btn task-detail-navbtn">
        {label} ↗
      </a>
    ) : (
      <button type="button" className="admin-btn task-detail-navbtn" disabled title={hint}>
        {label}
      </button>
    );

  return (
    <div className={`task-detail task-column--${task.status}`}>
      <div className="task-detail-summary">
        <div className="task-detail-top">
          <div className="task-detail-main">
          {assignError && <p className="admin-form-error">{assignError}</p>}
          <div className="task-detail-grid">
            {task.client_name && (
              <div className="task-detail-row">
                <span className="task-detail-label">Клиент</span>
                <span>{task.client_name}</span>
              </div>
            )}
            {task.car_description && (
              <div className="task-detail-row">
                <span className="task-detail-label">Автомобиль</span>
                <span>{task.car_description}</span>
              </div>
            )}
            {task.next_action_date && (
              <div className="task-detail-row">
                <span className="task-detail-label">Следующее действие</span>
                <span>{formatDate(task.next_action_date)}</span>
              </div>
            )}
            <div className="task-detail-row">
              <span className="task-detail-label">Сотрудник</span>
              <select
                className="task-detail-select"
                value={assigning ? assignEmployee : (task.employee_id ?? "")}
                disabled={!assigning}
                onChange={(event) => setAssignEmployee(event.target.value)}
                aria-label="Сотрудник"
              >
                <option value="">Не выбран</option>
                {employeesOfWorkshop(employees, (assigning ? assignWorkshop : task.workshop_id) || null).map(
                  (employee) => (
                    <option key={employee.id} value={employee.id}>
                      {employee.full_name}
                      {employee.specialty ? ` — ${employee.specialty}` : ""}
                    </option>
                  ),
                )}
              </select>
            </div>
            <div className="task-detail-row">
              <span className="task-detail-label">Цех</span>
              <select
                className="task-detail-select"
                value={assigning ? assignWorkshop : (task.workshop_id ?? "")}
                disabled={!assigning}
                onChange={(event) => {
                  const next = event.target.value;
                  setAssignWorkshop(next);
                  // Сотрудник остаётся, только если работает в новом цехе (или цех ему не указан).
                  const keep = employees.find((e) => e.id === assignEmployee);
                  if (keep?.workshop_id && keep.workshop_id !== next) setAssignEmployee("");
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
            <div className="task-detail-row">
              <span className="task-detail-label">Звонок</span>
              <span>{formatMoment(task.call_at, true)}</span>
            </div>
            <div className="task-detail-row">
              <span className="task-detail-label">На доске</span>
              <span>
                {task.moved_by_name ?? task.created_by_name}, в столбце с {formatMoment(task.status_changed_at, true)}
              </span>
            </div>
            {task.inspection_at && (
              <div className="task-detail-row">
                <span className="task-detail-label">Запись на осмотр</span>
                <span>
                  создана {formatMoment(task.inspection_at, true)}
                  {task.inspection_date &&
                    `, осмотр ${formatInspection(task.inspection_date, task.inspection_end_date)}`}
                </span>
              </div>
            )}
            {numberRow("Заявка на ремонт", task.request_number)}
            {numberRow("Заказ-наряд", task.work_order_number)}
          </div>
          </div>
            {/* Кнопки всегда в одном месте справа; поля ниже только разблокируются. */}
            <span className="task-detail-head-actions">
              {assigning ? (
                <span className="task-detail-head-row">
                  <button
                    type="button"
                    className="admin-btn admin-btn-primary"
                    disabled={saving || !assignWorkshop}
                    onClick={() => void saveAssign()}
                  >
                    {saving ? "Сохраняем…" : "Сохранить"}
                  </button>
                  <button type="button" className="admin-btn" disabled={saving} onClick={() => setAssigning(false)}>
                    Отмена
                  </button>
                </span>
              ) : (
                <button type="button" className="admin-btn task-detail-navbtn" onClick={startAssign}>
                  Изменить
                </button>
              )}
              {navButton("Запись на осмотр", plannerHref, "Записи в планировщике пока нет")}
              {navButton(
                "Заявка на ремонт",
                detail?.request_id ? `/work-orders/${detail.request_id}` : null,
                "Заявки на ремонт пока нет",
              )}
              {navButton(
                "Заказ-наряд",
                detail?.work_order_id ? `/work-orders/${detail.work_order_id}` : null,
                "Заказ-наряда пока нет",
              )}
            </span>
        </div>
        {task.status === "refused" && task.refuse_reason && (
          <div className="task-detail-refusal">
            <strong>Причина отказа</strong>
            <p>{task.refuse_reason}</p>
          </div>
        )}
        {detailError && <p className="admin-form-error">{detailError}</p>}
      </div>

      <button
        type="button"
        className="task-detail-toggle"
        aria-expanded={callsOpen}
        onClick={() => setCallsOpen((prev) => !prev)}
      >
        {callsOpen ? "▾" : "▸"} Звонки{calls ? ` (${calls.length})` : ""}
      </button>
      {callsOpen && (
        <>
          {callsError && <p className="admin-form-error">{callsError}</p>}
          {!calls && !callsError && <p className="admin-hint">Загрузка…</p>}
          {calls && calls.length === 0 && <p className="admin-hint">Звонков не найдено</p>}
          {calls && calls.length > 0 && (
            <div className="task-detail-calls">
              <CallEventsTable events={calls} showControl={false} defaultSortDir="desc" />
            </div>
          )}
        </>
      )}

      <button
        type="button"
        className="task-detail-toggle"
        aria-expanded={commentsOpen}
        onClick={() => setCommentsOpen((prev) => !prev)}
      >
        {commentsOpen ? "▾" : "▸"} Комментарии ({comments.length})
      </button>
      {commentsOpen && (
        <>
          <div className="task-detail-comment-form">
            <textarea
              rows={3}
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) void addComment();
              }}
              placeholder="Написать комментарий…  (Ctrl+Enter - отправить)"
              aria-label="Комментарий"
            />
            <div className="request-control-actions">
              <button
                type="button"
                className="admin-btn admin-btn-primary"
                disabled={saving || !text.trim()}
                onClick={() => void addComment()}
              >
                {saving ? "Сохраняем…" : "Добавить комментарий"}
              </button>
            </div>
            {commentError && !actionsOpen && <p className="admin-form-error">{commentError}</p>}
          </div>
          <ul className="task-detail-comments">
            {comments.length === 0 && <li className="admin-hint">Комментариев пока нет</li>}
            {comments.map((comment) => {
              const stage = columnOf(comment.status);
              return (
                <li key={comment.id} className={`task-detail-comment task-column--${comment.status}`}>
                  <div className="task-detail-comment-head">
                    <strong>{comment.author_name}</strong>
                    <span>{formatMoment(comment.created_at, true)}</span>
                    <span className="task-detail-comment-stage">
                      {stage.icon} {stage.title}
                    </span>
                  </div>
                  <p>{comment.text}</p>
                </li>
              );
            })}
          </ul>
        </>
      )}

      <button
        type="button"
        className="task-detail-toggle"
        aria-expanded={actionsOpen}
        onClick={() => setActionsOpen((prev) => !prev)}
      >
        {actionsOpen ? "▾" : "▸"} Действия ({actions.length})
      </button>
      {actionsOpen && (
        <>
          <div className="task-detail-comment-form">
            <div className="task-detail-plan">
              <label htmlFor={`task-next-date-${task.id}`}>Дата контакта</label>
              <DateInput id={`task-next-date-${task.id}`} value={nextDate} onChange={setNextDate} />
              <span className="admin-hint">
                {task.next_action_date
                  ? `Сейчас запланировано на ${formatDate(task.next_action_date)}: в этот день карточка станет розовой.`
                  : "Не запланировано - сроки считаются от перевода на контроль."}
              </span>
            </div>
            <textarea
              rows={3}
              value={planText}
              onChange={(event) => setPlanText(event.target.value)}
              placeholder="Что нужно сделать (комментарий обязателен)"
              aria-label="Комментарий к запланированному действию"
            />
            <div className="request-control-actions">
              <button
                type="button"
                className="admin-btn admin-btn-primary"
                disabled={saving || !nextDate || !planText.trim()}
                onClick={() => void addAction()}
              >
                {saving ? "Сохраняем…" : "Запланировать"}
              </button>
            </div>
            {commentError && actionsOpen && <p className="admin-form-error">{commentError}</p>}
          </div>
        <ul className="task-detail-comments">
          {actions.length === 0 && <li className="admin-hint">Действий пока не планировали</li>}
          {actions.map((action, index) => (
            <li key={action.id} className="task-detail-comment task-column--control">
              <div className="task-detail-comment-head">
                <strong>На {formatDate(action.planned_date)}</strong>
                <span>
                  {action.author_name}, {formatMoment(action.created_at, true)}
                </span>
                {index === 0 && <span className="task-detail-comment-stage">действует</span>}
              </div>
              {editId === action.id ? (
                <div className="task-detail-edit">
                  <label htmlFor={`task-edit-date-${action.id}`}>Дата контакта</label>
                  <DateInput id={`task-edit-date-${action.id}`} value={editDate} onChange={setEditDate} />
                  <label htmlFor={`task-edit-text-${action.id}`}>Комментарий</label>
                  <textarea
                    id={`task-edit-text-${action.id}`}
                    rows={6}
                    value={editText}
                    onChange={(event) => setEditText(event.target.value)}
                  />
                  <div className="request-control-actions">
                  <button
                    type="button"
                    className="admin-btn admin-btn-primary"
                    disabled={saving || !editDate || !editText.trim()}
                    onClick={() => void saveAction()}
                  >
                    Сохранить
                  </button>
                  <button type="button" className="admin-btn" onClick={() => setEditId(null)}>
                    Отмена
                  </button>
                  </div>
                </div>
              ) : (
                <>
                  <p>{action.comment}</p>
                  <div className="request-control-actions">
                    <button
                      type="button"
                      className="admin-btn"
                      onClick={() => {
                        setEditId(action.id);
                        setEditDate(action.planned_date);
                        setEditText(action.comment);
                      }}
                    >
                      Изменить
                    </button>
                    <button type="button" className="admin-btn" onClick={() => void removeAction(action.id)}>
                      Удалить
                    </button>
                  </div>
                </>
              )}
            </li>
          ))}
          {actionError && <li className="admin-form-error">{actionError}</li>}
        </ul>
        </>
      )}
    </div>
  );
}
