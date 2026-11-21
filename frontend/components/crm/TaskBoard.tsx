"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ManualTaskDialog, type ManualTaskResult } from "@/components/crm/ManualTaskDialog";
import {
  employeesOfWorkshop,
  useControlTasks,
  useEmployees,
  workshopLabel,
} from "@/components/crm/WorkshopsContext";
import {
  COLUMNS,
  canMoveByHand,
  formatDate,
  formatInspection,
  formatMoment,
  formatPhone,
  sourceTitle,
  type Column,
} from "@/components/crm/columns";
import { TaskDetailModal } from "@/components/crm/TaskDetailModal";
import { AdminModal } from "@/components/settings/AdminModal";
import { InspectionBookingDialog } from "@/components/crm/InspectionBookingDialog";
import type {
  CrmTask,
  CrmTaskListResponse,
  CrmTaskStatus,
  Employee,
  SlesarkaStatus,
  Workshop,
} from "@/lib/backend-api";

const REFRESH_MS = 60_000;
const ALL_WORKSHOPS = "";

/** "2 дн. 3 ч" / "5 ч" / "меньше часа" - how long the card has been in its column. */
function formatAge(iso: string, now: number): string {
  const minutes = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60_000));
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  if (days > 0) return hours > 0 ? `${days} дн. ${hours} ч` : `${days} дн.`;
  if (hours > 0) return `${hours} ч`;
  return "меньше часа";
}

function cardClass(task: CrmTask, highlightId: string | null): string {
  const classes = ["task-card"];
  if (highlightId) classes.push(task.id === highlightId ? "task-card--focus" : "task-card--dim");
  if (task.alert === "warn") classes.push("task-card--warn");
  if (task.alert === "overdue") classes.push("task-card--overdue");
  return classes.join(" ");
}

/** Доска задач CRM (product ask, 2026-11-15): телефоны, взятые на контроль со звонка, по
 * столбцам. Карточки сами уходят вперёд (запись на осмотр в планировщике -> заявка на ремонт ->
 * заказ-наряд, всё только позже звонка - считает бэкенд), руками их можно перетаскивать; в «Отказ»
 * - с обязательной причиной, в «Заказ-наряд» руками нельзя. Цех - фильтр сверху: пользователя
 * или «Все». */
export function TaskBoard({
  workshops,
  initialWorkshopId,
  employees,
  initialEmployeeId,
  slesarkaStatuses,
  fivesystemsApiEnabled,
  highlightId = null,
  onClearHighlight,
  active = true,
}: {
  workshops: Workshop[];
  /** The user's own цех or the one from a deep link (planner badge); "Все" if none. */
  initialWorkshopId?: string | null;
  employees: Employee[];
  /** The user's own employee; null ("Все") for Админ / Управляющий. */
  initialEmployeeId?: string | null;
  /** For the planner's record form opened by dragging a card to «Записан на осмотр». */
  slesarkaStatuses: SlesarkaStatus[];
  fivesystemsApiEnabled: boolean;
  /** A card shown from the calls' status button: it stays bright, the others are dimmed. */
  highlightId?: string | null;
  onClearHighlight?: () => void;
  /** The board's tab is the one shown. The tabs stay mounted, so a card put on control from "Звонки"
   * would not show up until the next poll: every switch to the board reloads it, and the periodic
   * poll runs only while it is visible. */
  active?: boolean;
}) {
  const [workshopId, setWorkshopId] = useState(
    initialWorkshopId && workshops.some((w) => w.id === initialWorkshopId) ? initialWorkshopId : ALL_WORKSHOPS,
  );
  const [employeeId, setEmployeeId] = useState(
    initialEmployeeId &&
      employeesOfWorkshop(
        employees,
        initialWorkshopId && workshops.some((w) => w.id === initialWorkshopId) ? initialWorkshopId : null,
      ).some((e) => e.id === initialEmployeeId)
      ? initialEmployeeId
      : ALL_WORKSHOPS,
  );
  const employeeOptions = useMemo(
    () => employeesOfWorkshop(employees, workshopId || null),
    [employees, workshopId],
  );
  // «Отказ» / «Заказ-наряд» старше срока из настроек уходят с доски в архив; галка возвращает их.
  const [showArchived, setShowArchived] = useState(false);
  const [data, setData] = useState<CrmTaskListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [dragId, setDragId] = useState<string | null>(null);
  const [overColumn, setOverColumn] = useState<CrmTaskStatus | null>(null);
  const [refusing, setRefusing] = useState<CrmTask | null>(null);
  // Dragged from «На контроле» to «Записан на осмотр»: the planner's record form of its цех.
  const [booking, setBooking] = useState<CrmTask | null>(null);
  // Клик по карточке открывает окно лида: звонки, ссылки, комментарии.
  const [opened, setOpened] = useState<CrmTask | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  // «Создать»: карточка руками; цех и сотрудник по умолчанию - текущего пользователя.
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const { currentEmployeeId } = useEmployees();
  const { register } = useControlTasks();
  const ownEmployee = employees.find((e) => e.id === currentEmployeeId) ?? null;
  const createWorkshopId =
    ownEmployee?.workshop_id && workshops.some((w) => w.id === ownEmployee.workshop_id)
      ? ownEmployee.workshop_id
      : workshopId;
  const createEmployeeId =
    ownEmployee &&
    (!ownEmployee.workshop_id || ownEmployee.workshop_id === createWorkshopId) &&
    createWorkshopId
      ? ownEmployee.id
      : "";
  const manualDone = (result: ManualTaskResult) => {
    setCreating(false);
    register(result.task);
    void load();
    if (result.created) {
      const linked =
        result.linked === "call"
          ? " Телефон найден в телефонии, задача связана со звонком."
          : result.linked === "lead"
            ? " Телефон найден среди заявок с сайта, задача связана с заявкой."
            : "";
      setNotice(`Задача создана.${linked}`);
    } else {
      setNotice("Этот телефон уже на доске - открыта существующая задача.");
      setOpened(result.task);
    }
  };
  // Responses of an older filter must not overwrite a newer one.
  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    try {
      const query = new URLSearchParams();
      if (workshopId) query.set("workshop_id", workshopId);
      if (employeeId) query.set("employee_id", employeeId);
      if (showArchived) query.set("archived", "1");
      const res = await fetch(`/api/crm-tasks?${query.toString()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`${res.status}`);
      const next = (await res.json()) as CrmTaskListResponse;
      if (seq !== requestSeq.current) return;
      setData(next);
      setNow(Date.now());
      setError(null);
    } catch {
      if (seq === requestSeq.current) setError("Не удалось загрузить доску задач");
    }
  }, [workshopId, employeeId, showArchived]);

  useEffect(() => {
    if (!active) return;
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load, active]);

  // A highlighted card must be visible: drop the filters, and bring it into view once loaded.
  useEffect(() => {
    if (!highlightId) return;
    setWorkshopId(ALL_WORKSHOPS);
    setEmployeeId(ALL_WORKSHOPS);
  }, [highlightId]);
  const highlightedReady = highlightId ? (data?.items.some((t) => t.id === highlightId) ?? false) : false;
  useEffect(() => {
    if (!highlightId || !highlightedReady || !active) return;
    document.getElementById(`task-card-${highlightId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlightId, highlightedReady, active]);

  const byColumn = useMemo(() => {
    const groups = new Map<CrmTaskStatus, CrmTask[]>(COLUMNS.map((c) => [c.key, []]));
    for (const task of data?.items ?? []) groups.get(task.status)?.push(task);
    // "На контроле": самые давние сверху (их надо обработать первыми); остальные - свежие сверху.
    for (const [key, tasks] of groups) {
      tasks.sort((a, b) => {
        const diff = new Date(a.status_changed_at).getTime() - new Date(b.status_changed_at).getTime();
        return key === "control" ? diff : -diff;
      });
    }
    return groups;
  }, [data]);

  const patchTask = (updated: CrmTask) =>
    setData((prev) =>
      prev ? { ...prev, items: prev.items.map((task) => (task.id === updated.id ? updated : task)) } : prev,
    );

  const move = async (
    task: CrmTask,
    target: CrmTaskStatus,
    moveReason?: string,
    link?: { body_car_id?: string; workshop_job_id?: string },
  ): Promise<string | null> => {
    try {
      const res = await fetch(`/api/crm-tasks/${task.id}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: target, reason: moveReason ?? null, ...link }),
      });
      const body = (await res.json()) as CrmTask & { error?: string };
      if (!res.ok) return body.error ?? "Не удалось перенести задачу";
      patchTask(body);
      // The page may be out of date (cards that moved by themselves) - refresh quietly.
      void load();
      return null;
    } catch {
      return "Не удалось перенести задачу";
    }
  };

  const drop = async (column: Column) => {
    const task = data?.items.find((item) => item.id === dragId);
    setDragId(null);
    setOverColumn(null);
    if (!task || !canMoveByHand(task.status, column.key)) return;
    if (column.needsReason) {
      setReason("");
      setDialogError(null);
      setRefusing(task);
      return;
    }
    if (column.key === "inspection") {
      setError(null);
      setBooking(task);
      return;
    }
    if (column.key === "control" && task.status === "inspection" && task.planner_record) {
      if (!window.confirm("Запись в планировщике будет удалена. Вернуть на контроль?")) return;
    }
    const failure = await move(task, column.key);
    setError(failure);
  };

  const confirmRefusal = async () => {
    if (!refusing) return;
    setSaving(true);
    const failure = await move(refusing, "refused", reason);
    setSaving(false);
    if (failure) {
      setDialogError(failure);
      return;
    }
    setRefusing(null);
    setError(null);
  };

  const canDrop = (column: Column): boolean => {
    const task = data?.items.find((item) => item.id === dragId);
    return task ? canMoveByHand(task.status, column.key) : false;
  };

  return (
    <div className="task-board">
      {highlightId && (
        <div className="task-board-highlight">
          Показана задача по звонку, остальные приглушены.
          <button type="button" className="admin-btn" onClick={onClearHighlight}>
            Показать все
          </button>
        </div>
      )}
      <div className="task-board-toolbar">
        <button
          type="button"
          className="admin-btn admin-btn-primary"
          onClick={() => {
            setNotice(null);
            setCreating(true);
          }}
        >
          Создать
        </button>
        <label className="task-board-filter">
          Цех
          <select
            value={workshopId}
            onChange={(event) => {
              const next = event.target.value;
              setWorkshopId(next);
              // The chosen employee stays only if they work in the new цех.
              if (employeeId && !employeesOfWorkshop(employees, next || null).some((e) => e.id === employeeId)) {
                setEmployeeId(ALL_WORKSHOPS);
              }
            }}
            aria-label="Фильтр по цеху"
          >
            <option value={ALL_WORKSHOPS}>Все</option>
            {workshops.map((workshop) => (
              <option key={workshop.id} value={workshop.id}>
                {workshopLabel(workshop)}
              </option>
            ))}
          </select>
        </label>
        <label className="task-board-filter">
          Сотрудник
          <select
            value={employeeId}
            onChange={(event) => setEmployeeId(event.target.value)}
            aria-label="Фильтр по сотруднику"
          >
            <option value={ALL_WORKSHOPS}>Все</option>
            {employeeOptions.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employee.full_name}
              </option>
            ))}
          </select>
        </label>
        <label className="task-board-archive">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(event) => setShowArchived(event.target.checked)}
          />
          Показать архивные
        </label>
        {data && (
          <span className="task-board-legend">
            <span className="task-board-dot task-board-dot--warn" /> на контроле от {data.warn_days} дн.
            <span className="task-board-dot task-board-dot--overdue" /> от {data.overdue_days} дн.
          </span>
        )}
      </div>

      {error && <p className="admin-form-error">{error}</p>}
      {notice && <p className="admin-hint">{notice}</p>}
      {!data && !error && <p className="admin-hint">Загрузка…</p>}

      {data && (
        <div className="task-board-columns">
          {COLUMNS.map((column) => {
            const tasks = byColumn.get(column.key) ?? [];
            return (
              <section
                key={column.key}
                className={[
                  "task-column",
                  `task-column--${column.key}`,
                  // Пока тащим карточку, подходящие столбцы подсвечены на всю высоту.
                  dragId && canDrop(column) ? "task-column--target" : "",
                  overColumn === column.key && canDrop(column) ? "task-column--over" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onDragOver={(event) => {
                  if (!canDrop(column)) return;
                  event.preventDefault();
                  if (overColumn !== column.key) setOverColumn(column.key);
                }}
                onDragLeave={(event) => {
                  if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOverColumn(null);
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  void drop(column);
                }}
              >
                <h3 className="task-column-title">
                  <span>
                    <span className="task-column-icon" aria-hidden="true">
                      {column.icon}
                    </span>
                    {column.title}
                  </span>
                  <span className="task-column-count">{tasks.length}</span>
                </h3>
                <div className="task-column-body">
                  {tasks.length === 0 && <p className="task-column-empty">—</p>}
                  {tasks.map((task) => (
                    <article
                      key={task.id}
                      id={`task-card-${task.id}`}
                      className={cardClass(task, highlightId)}
                      onClick={() => setOpened(task)}
                      draggable
                      onDragStart={(event) => {
                        event.dataTransfer.effectAllowed = "move";
                        event.dataTransfer.setData("text/plain", task.id);
                        setDragId(task.id);
                      }}
                      onDragEnd={() => {
                        setDragId(null);
                        setOverColumn(null);
                      }}
                    >
                      <div className="task-card-phone">{formatPhone(task.phone)}</div>
                      {task.client_name && <div className="task-card-line">{task.client_name}</div>}
                      {task.car_description && <div className="task-card-line">{task.car_description}</div>}
                      {task.status === "control" && task.next_action_date && (
                        <div className="task-card-line">
                          Следующее действие: {formatDate(task.next_action_date)}
                        </div>
                      )}
                      {task.inspection_date && (
                        <div className="task-card-line">
                          Осмотр: {formatInspection(task.inspection_date, task.inspection_end_date)}
                        </div>
                      )}
                      {task.inspection_at && (
                        <div className="task-card-meta">Записан: {formatMoment(task.inspection_at, true)}</div>
                      )}
                      {task.request_number && (
                        <div className="task-card-line">Заявка на ремонт: {task.request_number}</div>
                      )}
                      {task.work_order_number && (
                        <div className="task-card-line">Заказ-наряд: {task.work_order_number}</div>
                      )}
                      {task.refuse_reason && (
                        <div className="task-card-line">Причина: {task.refuse_reason}</div>
                      )}
                      <div className="task-card-meta">
                        {sourceTitle(task.source)} {formatMoment(task.call_at)}
                        {task.status === "control" && <> · на контроле {formatAge(task.status_changed_at, now)}</>}
                      </div>
                      {task.employee_name && <div className="task-card-meta">Сотрудник: {task.employee_name}</div>}
                      {!workshopId && task.workshop_label && (
                        <div className="task-card-meta">{task.workshop_label}</div>
                      )}
                      <div className="task-card-meta">
                        {task.moved_by_name ?? task.created_by_name}
                        {task.comments_count > 0 && (
                          <span className="task-card-comments" title="Комментарии">
                            💬 {task.comments_count}
                          </span>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}

      <InspectionBookingDialog
        task={booking}
        workshop={workshops.find((w) => w.id === booking?.workshop_id) ?? null}
        employees={employees}
        statuses={slesarkaStatuses}
        fivesystemsApiEnabled={fivesystemsApiEnabled}
        onClose={() => setBooking(null)}
        onMove={async (task, link) => {
          const failure = await move(task, "inspection", undefined, link);
          if (!failure) setBooking(null);
          return failure;
        }}
      />

      {creating && (
        <ManualTaskDialog
          workshops={workshops}
          employees={employees}
          defaultWorkshopId={createWorkshopId}
          defaultEmployeeId={createEmployeeId}
          onClose={() => setCreating(false)}
          onDone={manualDone}
        />
      )}

      <TaskDetailModal
        task={opened}
        onClose={() => setOpened(null)}
        onChanged={() => void load()}
        onCommentCountChange={(taskId, count) => {
          const patch = (item: CrmTask) => (item.id === taskId ? { ...item, comments_count: count } : item);
          setData((prev) => (prev ? { ...prev, items: prev.items.map(patch) } : prev));
          setOpened((prev) => (prev ? patch(prev) : prev));
        }}
      />

      <AdminModal
        open={refusing !== null}
        title="Отказ"
        onClose={() => {
          if (!saving) setRefusing(null);
        }}
      >
        {refusing && (
          <div className="task-refuse-dialog">
            <p className="admin-hint">{formatPhone(refusing.phone)}</p>
            <label htmlFor="task-refuse-reason">Причина отказа</label>
            <textarea
              id="task-refuse-reason"
              rows={4}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Обязательно: почему клиент отказался"
              autoFocus
            />
            {dialogError && <p className="admin-form-error">{dialogError}</p>}
            <div className="request-control-actions">
              <button
                type="button"
                className="admin-btn admin-btn-danger"
                disabled={saving || !reason.trim()}
                onClick={() => void confirmRefusal()}
              >
                {saving ? "Сохраняем…" : "Перенести в «Отказ»"}
              </button>
              <button type="button" className="admin-btn" disabled={saving} onClick={() => setRefusing(null)}>
                Отмена
              </button>
            </div>
          </div>
        )}
      </AdminModal>
    </div>
  );
}
