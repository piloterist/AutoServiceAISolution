"use client";

import { useCallback, useEffect, useState } from "react";

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
      title={task ? `Лид · ${formatPhone(task.phone)}` : "Лид"}
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
  const [historyOpen, setHistoryOpen] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [text, setText] = useState("");
  // «Запланировать действие»: пусто по умолчанию; с датой комментарий обязателен.
  const [nextDate, setNextDate] = useState("");
  const [saving, setSaving] = useState(false);
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

  const addComment = async () => {
    const value = text.trim();
    if (!value) return;
    setSaving(true);
    setCommentError(null);
    try {
      const res = await fetch(`/api/crm-tasks/${task.id}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: value, next_action_date: nextDate || null }),
      });
      const body = (await res.json()) as CrmTaskComment & { error?: string };
      if (!res.ok) throw new Error(body.error ?? "Не удалось сохранить комментарий");
      const planned = Boolean(nextDate);
      setText("");
      setNextDate("");
      setHistoryOpen(true);
      if (planned) setActionsOpen(true);
      const fresh = await loadDetail();
      onCommentCountChange(task.id, fresh.comments.length);
      onChanged();
    } catch (err) {
      setCommentError(err instanceof Error ? err.message : "Не удалось сохранить комментарий");
    } finally {
      setSaving(false);
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

  const link = (label: string, number: string | null, id: string | null | undefined) =>
    number && (
      <div className="task-detail-row">
        <span className="task-detail-label">{label}</span>
        {id ? (
          <a href={`/work-orders/${id}`} className="task-detail-link task-detail-linkbtn">
            {number} ↗
          </a>
        ) : (
          <span>{number}</span>
        )}
      </div>
    );

  return (
    <div className={`task-detail task-column--${task.status}`}>
      <div className="task-detail-summary">
        <span className="task-detail-stage">
          <span aria-hidden="true">{column.icon}</span> {column.title}
        </span>
        <div className="task-detail-grid">
          <div className="task-detail-row">
            <span className="task-detail-label">Телефон</span>
            <span>{formatPhone(task.phone)}</span>
          </div>
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
          {task.employee_name && (
            <div className="task-detail-row">
              <span className="task-detail-label">Сотрудник</span>
              <span>{task.employee_name}</span>
            </div>
          )}
          {task.workshop_label && (
            <div className="task-detail-row">
              <span className="task-detail-label">Цех</span>
              <span>{task.workshop_label}</span>
            </div>
          )}
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
                {plannerHref && (
                  <>
                    {" "}
                    <a href={plannerHref} className="task-detail-link task-detail-linkbtn">
                      Запись на осмотр ↗
                    </a>
                  </>
                )}
              </span>
            </div>
          )}
          {link("Заявка на ремонт", task.request_number, detail?.request_id)}
          {link("Заказ-наряд", task.work_order_number, detail?.work_order_id)}
        </div>
        {task.status === "refused" && task.refuse_reason && (
          <div className="task-detail-refusal">
            <strong>Причина отказа</strong>
            <p>{task.refuse_reason}</p>
          </div>
        )}
        {detailError && <p className="admin-form-error">{detailError}</p>}
      </div>

      <h4 className="task-detail-heading">Звонки{calls ? ` (${calls.length})` : ""}</h4>
      {callsError && <p className="admin-form-error">{callsError}</p>}
      {!calls && !callsError && <p className="admin-hint">Загрузка…</p>}
      {calls && calls.length === 0 && <p className="admin-hint">Звонков не найдено</p>}
      {calls && calls.length > 0 && (
        <div className="task-detail-calls">
          <CallEventsTable events={calls} showControl={false} defaultSortDir="desc" />
        </div>
      )}

      <h4 className="task-detail-heading">Комментарии</h4>
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
        <h4 className="task-detail-heading">Запланировать действие</h4>
        <div className="task-detail-plan">
          <label htmlFor={`task-next-date-${task.id}`}>Дата контакта</label>
          <input
            id={`task-next-date-${task.id}`}
            type="date"
            value={nextDate}
            onChange={(event) => setNextDate(event.target.value)}
          />
          {nextDate && (
            <button type="button" className="admin-btn" onClick={() => setNextDate("")}>
              Очистить
            </button>
          )}
          <span className="admin-hint">
            {nextDate && !text.trim()
              ? "С датой комментарий обязателен - напишите его выше."
              : task.next_action_date
                ? `Сейчас запланировано на ${formatDate(task.next_action_date)}: в этот день карточка станет розовой.`
                : "Пусто - сроки считаются от перевода на контроль."}
          </span>
        </div>
        <div className="request-control-actions">
          <button
            type="button"
            className="admin-btn admin-btn-primary"
            disabled={saving || !text.trim()}
            onClick={() => void addComment()}
          >
            {saving ? "Сохраняем…" : nextDate ? "Запланировать и сохранить" : "Добавить комментарий"}
          </button>
          <button type="button" className="admin-btn" onClick={() => setHistoryOpen((prev) => !prev)}>
            {historyOpen ? "Скрыть историю" : `История комментариев (${comments.length})`}
          </button>
          <button type="button" className="admin-btn" onClick={() => setActionsOpen((prev) => !prev)}>
            {actionsOpen ? "Скрыть запланированные" : `Запланированные действия (${actions.length})`}
          </button>
        </div>
        {commentError && <p className="admin-form-error">{commentError}</p>}
      </div>

      {actionsOpen && (
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
                <div className="task-detail-plan">
                  <input type="date" value={editDate} onChange={(event) => setEditDate(event.target.value)} />
                  <textarea rows={2} value={editText} onChange={(event) => setEditText(event.target.value)} />
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
      )}

      {historyOpen && (
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
      )}
    </div>
  );
}
