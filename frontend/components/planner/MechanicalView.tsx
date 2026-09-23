"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { DateInput } from "@/components/DateInput";
import type { Employee, SlesarkaStatus, Workshop, WorkshopJob, WorkshopJobWrite } from "@/lib/backend-api";
import { workshopJobsApi } from "@/lib/planner-client";
import {
  addDaysIso,
  formatLongDay,
  minutesToTime,
  roundToSlot,
  timeToMinutes,
  todayIso,
} from "@/lib/planner-time";

import { emptyJobDraft, jobToDraft, WorkshopJobDialog, type JobDraft } from "./WorkshopJobDialog";

const SLOT_MINUTES = 30;
const SLOT_HEIGHT = 36;
// Pointer movement (px) below which a press+release is treated as a click
// (open the edit dialog) rather than a drag.
const DRAG_THRESHOLD_PX = 4;

type ViewSpan = 1 | 3 | 7;

type DragKind = "move" | "resize-start" | "resize-end";

type DragState = {
  kind: DragKind;
  job: WorkshopJob;
  pointerId: number;
  grabOffsetMinutes: number;
  // Pixel offset from the card's own top-left corner to where it was
  // grabbed, so the ghost tracks the cursor at the same point instead of
  // snapping its corner to it. Only meaningful for kind "move".
  grabPxX: number;
  grabPxY: number;
  cardWidth: number;
  cardHeight: number;
  startClientX: number;
  startClientY: number;
  clientX: number;
  clientY: number;
  hasMoved: boolean;
  // Re-resolved on every pointermove (not just once at drop - a single
  // elementFromPoint() read exactly at pointerup proved unreliable) so the
  // last-known-good column found while actually moving is what gets
  // committed. Only used for kind "move".
  targetDay: string | null;
  targetPost: number | null;
  // Live preview while resizing (minutes since midnight) - used for kinds
  // "resize-start"/"resize-end" to redraw the card's own top/height as the
  // user drags; irrelevant for "move" (the ghost follows the cursor there).
  previewStartMinutes: number;
  previewEndMinutes: number;
};

function jobMatches(job: WorkshopJob, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [job.work_order_number, job.car_description, job.vin]
    .filter(Boolean)
    .some((field) => field!.toLowerCase().includes(q));
}

/** Wraps MechanicalViewInner and forces a full remount of it (fresh state,
 * fresh useEffect, fresh fetch) after every write, by bumping `key` -
 * this replicates exactly what a full window.location.reload() was doing
 * (which reliably showed the correct post-write data, while a plain
 * in-place setJobs() from a client-side re-fetch reliably did not, for
 * reasons neither a caching fix on the fetch nor an audit of the backend
 * turned up), but without a visible page reload or losing the operator's
 * selected department/цех (PlannerShell, the parent, never remounts). */
export function MechanicalView(props: {
  workshop: Workshop;
  statuses: SlesarkaStatus[];
  employees: Employee[];
  fivesystemsApiEnabled: boolean;
}) {
  const [instanceKey, setInstanceKey] = useState(0);
  return <MechanicalViewInner key={instanceKey} {...props} onWritten={() => setInstanceKey((k) => k + 1)} />;
}

function MechanicalViewInner({
  workshop,
  statuses,
  employees,
  fivesystemsApiEnabled,
  onWritten,
}: {
  workshop: Workshop;
  statuses: SlesarkaStatus[];
  employees: Employee[];
  fivesystemsApiEnabled: boolean;
  onWritten: () => void;
}) {
  const [viewSpan, setViewSpan] = useState<ViewSpan>(7);
  // По умолчанию неделя открывается со вчерашнего дня (не с понедельника) -
  // самый ходовой вариант: видно "что было вчера" и весь ближайший план.
  const [currentDate, setCurrentDate] = useState(() => addDaysIso(todayIso(), -1));
  const [search, setSearch] = useState("");
  const [jobs, setJobs] = useState<WorkshopJob[]>([]);
  const [dialogDraft, setDialogDraft] = useState<JobDraft | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dragError, setDragError] = useState<string | null>(null);
  // Pointer-events-based drag (not native HTML5 DnD - that API's drop
  // target resolution turned out unreliable over the per-slot cells added
  // for :hover, and its ghost image jumping around read as "форма прыгает"
  // with no visible confirmation the move actually landed).
  //
  // Uses setPointerCapture on the element that received pointerdown, with
  // onPointerMove/onPointerUp as ordinary React props on that SAME element
  // - not a previous version's window-level addEventListener wired up
  // through a useEffect keyed on drag state. That worked for exactly one
  // drag and then silently stopped doing anything on the next one; pointer
  // capture removes the whole subscribe/cleanup lifecycle this depended on
  // (the browser guarantees events keep reaching the captured element
  // regardless of where the cursor moves), so there's no re-subscription
  // step to get wrong between gestures.
  //
  // `dragState` is real state so the ghost/resize preview re-renders every
  // move; `dragStateRef` mirrors it so handlers already bound to the
  // captured element always read the latest values instead of a stale
  // closure from when the gesture started.
  const [dragState, setDragState] = useState<DragState | null>(null);
  const dragStateRef = useRef<DragState | null>(null);
  // Elements keyed "day|post", used to find the column under the cursor by
  // plain coordinate-vs-rect math instead of document.elementFromPoint().
  // elementFromPoint() hit-tests real DOM stacking (z-index, pointer-events,
  // whatever's actually on top at that pixel) and twice now that proved
  // unreliable for this - once resolving to the wrong column, once
  // (suspected) racing the render that hides the drag source from
  // hit-testing. Plain rect math has no such dependency.
  const colElsRef = useRef<Map<string, HTMLDivElement>>(new Map());

  const findColAt = (clientX: number, clientY: number): { day: string; post: number } | null => {
    for (const [key, el] of colElsRef.current) {
      const rect = el.getBoundingClientRect();
      if (clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom) {
        const sep = key.indexOf("|");
        return { day: key.slice(0, sep), post: Number(key.slice(sep + 1)) };
      }
    }
    return null;
  };

  const days = useMemo(
    () => Array.from({ length: viewSpan }, (_, i) => addDaysIso(currentDate, i)),
    [currentDate, viewSpan],
  );

  const statusById = useMemo(() => new Map(statuses.map((s) => [s.id, s])), [statuses]);

  // Includes the closing time itself as a trailing entry, so it renders as
  // one more real .hr-labeled row instead of a separately-styled bolted-on
  // label - the trailing entry is label-only (see creationSlots below).
  const slots = useMemo(() => {
    const start = timeToMinutes(workshop.start_time);
    const end = timeToMinutes(workshop.end_time);
    const out: number[] = [];
    for (let m = start; m <= end; m += SLOT_MINUTES) out.push(m);
    return out;
  }, [workshop.start_time, workshop.end_time]);

  // Slots a job can actually start in - excludes the trailing closing-time
  // entry from `slots`, which exists only to carry its label.
  const creationSlots = useMemo(() => slots.slice(0, -1), [slots]);

  const reload = () => {
    workshopJobsApi
      .list(workshop.id, days[0], days[days.length - 1])
      .then(setJobs)
      .catch(() => setJobs([]));
  };

  useEffect(reload, [workshop.id, days[0], days[days.length - 1]]); // eslint-disable-line react-hooks/exhaustive-deps

  const jobsFor = (day: string, post: number) =>
    jobs.filter((j) => j.job_date === day && j.post_number === post);

  const dayStats = (day: string) => {
    const dayJobs = jobs.filter((j) => j.job_date === day);
    // План: every record for the day, any status.
    const plan = dayJobs.reduce((sum, j) => sum + Number(j.amount ?? 0), 0);
    // Факт: only records the workshop itself has marked "Готова" - the
    // job's own scheduling status, not the linked work order's status in
    // 1C (a separate, unrelated lifecycle).
    const fact = dayJobs
      .filter((j) => j.status_name === "Готова")
      .reduce((sum, j) => sum + Number(j.amount ?? 0), 0);
    // Загрузка: booked hours for the day excluding "Отмена" (a cancelled
    // record was never actually going to consume post time), against the
    // day's total post-hours capacity.
    const bookedMinutes = dayJobs
      .filter((j) => j.status_name !== "Отмена")
      .reduce((sum, j) => sum + (timeToMinutes(j.end_time) - timeToMinutes(j.start_time)), 0);
    const capacity = workshop.posts_count * (timeToMinutes(workshop.end_time) - timeToMinutes(workshop.start_time));
    const load = capacity > 0 ? Math.round((bookedMinutes / capacity) * 100) : 0;
    return { plan, fact, load };
  };

  const openCreate = (day: string, post: number, startMinutes: number) => {
    const start = minutesToTime(startMinutes);
    const end = minutesToTime(Math.min(startMinutes + SLOT_MINUTES, timeToMinutes(workshop.end_time)));
    setDialogDraft(emptyJobDraft(day, post, start, end, statuses));
    setDialogOpen(true);
  };

  const openEdit = (job: WorkshopJob) => {
    setDialogDraft(jobToDraft(job));
    setDialogOpen(true);
  };

  const closeDialog = () => setDialogOpen(false);

  const save = async (write: WorkshopJobWrite) => {
    if (dialogDraft?.jobId) {
      await workshopJobsApi.update(dialogDraft.jobId, write);
    } else {
      await workshopJobsApi.create(workshop.id, write);
    }
    onWritten();
  };

  const remove = async () => {
    if (dialogDraft?.jobId) await workshopJobsApi.remove(dialogDraft.jobId);
    onWritten();
  };

  const dayEndMinutes = timeToMinutes(workshop.end_time);
  const dayStartMinutes = timeToMinutes(workshop.start_time);

  const startDrag = (e: React.PointerEvent<HTMLDivElement>, job: WorkshopJob, kind: DragKind) => {
    if (e.button !== 0) return;
    if (kind !== "move") e.stopPropagation(); // don't also trigger the card's own "move" pointerdown
    e.currentTarget.setPointerCapture(e.pointerId);
    const rect = e.currentTarget.getBoundingClientRect();
    const startMinutes = timeToMinutes(job.start_time);
    const endMinutes = timeToMinutes(job.end_time);
    const next: DragState = {
      kind,
      job,
      pointerId: e.pointerId,
      grabOffsetMinutes: roundToSlot(((e.clientY - rect.top) / SLOT_HEIGHT) * SLOT_MINUTES, SLOT_MINUTES),
      grabPxX: e.clientX - rect.left,
      grabPxY: e.clientY - rect.top,
      cardWidth: rect.width,
      cardHeight: rect.height,
      startClientX: e.clientX,
      startClientY: e.clientY,
      clientX: e.clientX,
      clientY: e.clientY,
      hasMoved: false,
      targetDay: job.job_date,
      targetPost: job.post_number,
      previewStartMinutes: startMinutes,
      previewEndMinutes: endMinutes,
    };
    dragStateRef.current = next;
    setDragState(next);
  };

  const handleDragPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const current = dragStateRef.current;
    if (!current || e.pointerId !== current.pointerId) return;
    const dx = e.clientX - current.startClientX;
    const dy = e.clientY - current.startClientY;
    const hasMoved = current.hasMoved || Math.hypot(dx, dy) > DRAG_THRESHOLD_PX;

    let targetDay = current.targetDay;
    let targetPost = current.targetPost;
    let previewStartMinutes = current.previewStartMinutes;
    let previewEndMinutes = current.previewEndMinutes;

    if (current.kind === "move") {
      // Re-resolve the column under the cursor on every move (not just
      // once at drop), so the drop always uses a column that was
      // genuinely under the cursor at some point during the gesture.
      if (hasMoved) {
        const found = findColAt(e.clientX, e.clientY);
        if (found) {
          targetDay = found.day;
          targetPost = found.post;
        }
      }
    } else {
      // resize-start/resize-end: vertical-only, day/post stay fixed - just
      // redraw this same card's own top/height live as the edge moves.
      const origStart = timeToMinutes(current.job.start_time);
      const origEnd = timeToMinutes(current.job.end_time);
      const deltaMinutes = roundToSlot((dy / SLOT_HEIGHT) * SLOT_MINUTES, SLOT_MINUTES);
      if (current.kind === "resize-start") {
        previewStartMinutes = Math.max(dayStartMinutes, Math.min(origStart + deltaMinutes, origEnd - SLOT_MINUTES));
      } else {
        previewEndMinutes = Math.min(dayEndMinutes, Math.max(origEnd + deltaMinutes, origStart + SLOT_MINUTES));
      }
    }

    const next = { ...current, clientX: e.clientX, clientY: e.clientY, hasMoved, targetDay, targetPost, previewStartMinutes, previewEndMinutes };
    dragStateRef.current = next;
    setDragState(next);
  };

  const finishDrag = (clientX: number, clientY: number) => {
    const dragging = dragStateRef.current;
    dragStateRef.current = null;
    setDragState(null);
    if (!dragging) return;

    if (!dragging.hasMoved) {
      if (dragging.kind === "move") openEdit(dragging.job);
      return;
    }

    let day = dragging.job.job_date;
    let post = dragging.job.post_number;
    let startMinutes: number;
    let endMinutes: number;

    if (dragging.kind === "move") {
      if (dragging.targetDay === null || dragging.targetPost === null) return;
      day = dragging.targetDay;
      post = dragging.targetPost;
      // Recompute the target column's rect fresh (not cached from an
      // earlier move) since scrolling can shift it between then and drop.
      const target = colElsRef.current.get(`${day}|${post}`);
      if (!target) return;
      const rect = target.getBoundingClientRect();
      const pointerMinutes = ((clientY - rect.top) / SLOT_HEIGHT) * SLOT_MINUTES;
      const duration = timeToMinutes(dragging.job.end_time) - timeToMinutes(dragging.job.start_time);
      let start = roundToSlot(dayStartMinutes + pointerMinutes - dragging.grabOffsetMinutes, SLOT_MINUTES);
      start = Math.max(dayStartMinutes, Math.min(start, dayEndMinutes - duration));
      startMinutes = start;
      endMinutes = start + duration;
    } else {
      startMinutes = dragging.previewStartMinutes;
      endMinutes = dragging.previewEndMinutes;
    }

    const startTime = `${minutesToTime(startMinutes)}:00`;
    const endTime = `${minutesToTime(endMinutes)}:00`;

    if (
      day === dragging.job.job_date &&
      post === dragging.job.post_number &&
      startTime === dragging.job.start_time &&
      endTime === dragging.job.end_time
    ) {
      return;
    }

    const write: WorkshopJobWrite = {
      work_order_id: dragging.job.work_order_id,
      car_description: dragging.job.car_description,
      vin: dragging.job.vin,
      plate: dragging.job.plate,
      client_name: dragging.job.client_name,
      phone: dragging.job.phone,
      employee_id: dragging.job.employee_id,
      work_description: dragging.job.work_description,
      job_date: day,
      post_number: post,
      start_time: startTime,
      end_time: endTime,
      norm_hours: dragging.job.norm_hours,
      status_id: dragging.job.status_id,
    };

    // Optimistic: move/resize the card immediately instead of waiting on
    // the round trip.
    setJobs((prev) =>
      prev.map((j) => (j.id === dragging.job.id ? { ...j, job_date: day, post_number: post, start_time: startTime, end_time: endTime } : j)),
    );

    workshopJobsApi.update(dragging.job.id, write).then(onWritten, (err) => {
      setDragError(err instanceof Error ? err.message : "Не удалось сохранить перенос записи");
      setTimeout(() => setDragError(null), 3000);
      reload();
    });
  };

  const handleDragPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const current = dragStateRef.current;
    if (!current || e.pointerId !== current.pointerId) return;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    finishDrag(e.clientX, e.clientY);
  };

  const colH = slots.length * SLOT_HEIGHT;
  const todayStr = todayIso();

  return (
    <div className="planner-flex-col">
      <div className="planner-toolbar">
        <div className="grp">
          <button type="button" onClick={() => setCurrentDate(addDaysIso(currentDate, -1))}>
            ‹
          </button>
          <button
            type="button"
            onClick={() => {
              setViewSpan(1);
              setCurrentDate(todayStr);
            }}
          >
            Сегодня
          </button>
          <button type="button" onClick={() => setCurrentDate(addDaysIso(currentDate, 1))}>
            ›
          </button>
          <DateInput value={currentDate} onChange={(iso) => iso && setCurrentDate(iso)} />
        </div>
        <div className="seg">
          {([1, 3, 7] as ViewSpan[]).map((span) => (
            <button
              key={span}
              type="button"
              className={span === viewSpan ? "on" : ""}
              onClick={() => setViewSpan(span)}
            >
              {span === 1 ? "1 день" : span === 3 ? "3 дня" : "Неделя"}
            </button>
          ))}
        </div>
        <div className="planner-legend">
          {statuses.map((s) => (
            <span key={s.id} className="planner-legend-item">
              <i style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
        </div>
        <div className="grp planner-search-grp">
          <input
            type="search"
            placeholder="Поиск автомобиля"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button type="button" onClick={() => setSearch("")}>
            Сбросить
          </button>
        </div>
      </div>

      {dragError && <p className="admin-form-error">{dragError}</p>}

      <div className="mscroll">
        <div
          className="mgrid"
          style={{ gridTemplateColumns: `62px repeat(${days.length * workshop.posts_count}, minmax(150px, 1fr))` }}
        >
          <div className="corner planner-corner-1" />
          {days.map((day) => {
            const stats = dayStats(day);
            return (
              <div
                key={day}
                className={day === todayStr ? "dayh today" : "dayh"}
                style={{ gridColumn: `span ${workshop.posts_count}` }}
              >
                <div className="planner-dayh-title">
                  <b>{formatLongDay(day)}</b>
                  {day === todayStr && <span className="dayh-badge">сегодня</span>}
                </div>
                <div className="planner-dayh-stats">
                  {/* План/Факт в рублях скрыты по просьбе - расчёт (dayStats
                      выше) не тронут, просто не выводится здесь. */}
                  <span>
                    Загрузка <b>{stats.load}%</b>
                  </span>
                </div>
              </div>
            );
          })}

          <div className="corner planner-corner-2" />
          {days.map((day) =>
            Array.from({ length: workshop.posts_count }, (_, i) => i + 1).map((post) => (
              <div key={`${day}-${post}`} className="posth">
                Пост {post}
              </div>
            )),
          )}

          <div className="timecol" style={{ height: colH }}>
            {slots.map((m) => (
              <div key={m} className={m % 60 === 0 ? "hr" : ""}>
                {m % 60 === 0 ? minutesToTime(m) : ""}
              </div>
            ))}
          </div>

          {days.map((day) =>
            Array.from({ length: workshop.posts_count }, (_, i) => i + 1).map((post) => (
              <div
                key={`${day}-${post}-col`}
                className={
                  dragState?.hasMoved && dragState.targetDay === day && dragState.targetPost === post
                    ? `${day === todayStr ? "col today" : "col"} planner-col-drop-target`
                    : day === todayStr
                      ? "col today"
                      : "col"
                }
                style={{ height: colH }}
                ref={(el) => {
                  const key = `${day}|${post}`;
                  if (el) colElsRef.current.set(key, el);
                  else colElsRef.current.delete(key);
                }}
              >
                {/* One real element per 30-minute slot so :hover highlights
                    exactly that slot, not the whole post/day column (each
                    slot already knows its own start time, no pixel math
                    needed for the click-to-create handler here). The
                    trailing closing-time entry in `slots` is excluded - it
                    exists only to label the time column, not a bookable
                    start. */}
                {creationSlots.map((m) => {
                  // A row's border-bottom sits at its END, not its start -
                  // the row that should get the dark "full hour" border is
                  // the one ENDING on the hour (m+30), not the one
                  // starting on it, or the dark line lands half an hour
                  // too early (at each :30 mark instead of each :00 mark).
                  const endsOnHour = (m + SLOT_MINUTES) % 60 === 0;
                  return (
                    <div
                      key={m}
                      className={endsOnHour ? "col-slot col-slot--hour" : "col-slot"}
                      style={{ height: SLOT_HEIGHT }}
                      onClick={() => openCreate(day, post, m)}
                    />
                  );
                })}
                {jobsFor(day, post).map((job) => {
                  const status = job.status_id ? statusById.get(job.status_id) : undefined;
                  const isBeingResized = dragState?.hasMoved && dragState.job.id === job.id && dragState.kind !== "move";
                  const startMinutes = isBeingResized ? dragState.previewStartMinutes : timeToMinutes(job.start_time);
                  const endMinutes = isBeingResized ? dragState.previewEndMinutes : timeToMinutes(job.end_time);
                  const top = ((startMinutes - timeToMinutes(workshop.start_time)) / SLOT_MINUTES) * SLOT_HEIGHT;
                  const height = ((endMinutes - startMinutes) / SLOT_MINUTES) * SLOT_HEIGHT - 2;
                  const dim = search.trim() && !jobMatches(job, search);
                  const isDragSource = dragState?.hasMoved && dragState.job.id === job.id && dragState.kind === "move";
                  return (
                    <div
                      key={job.id}
                      className={[dim ? "job planner-job-dim" : "job", isDragSource ? "planner-job-drag-source" : ""]
                        .filter(Boolean)
                        .join(" ")}
                      style={{
                        top,
                        height: Math.max(18, height),
                        // CC = 80% opaque (20% transparent) - the previous
                        // 33 suffix was ~20% opaque, so the card barely
                        // showed its status color at all.
                        background: status ? `${status.color}CC` : "var(--surface2)",
                        borderLeftColor: status ? status.color : "var(--border)",
                        touchAction: "none",
                      }}
                      onPointerDown={(e) => startDrag(e, job, "move")}
                      onPointerMove={handleDragPointerMove}
                      onPointerUp={handleDragPointerUp}
                      onPointerCancel={handleDragPointerUp}
                    >
                      {/* Grab the top/bottom edge to shrink or stretch the
                          record in time only - day/post stay fixed. */}
                      <div
                        className="job-resize-handle job-resize-handle--top"
                        onPointerDown={(e) => startDrag(e, job, "resize-start")}
                        onPointerMove={handleDragPointerMove}
                        onPointerUp={handleDragPointerUp}
                        onPointerCancel={handleDragPointerUp}
                      />
                      <div className="job-title">{job.work_order_number ?? "Без ЗН"}</div>
                      {job.car_description && <div className="job-sub">{job.car_description}</div>}
                      {job.work_description && <div className="job-work">{job.work_description}</div>}
                      {job.employee_name && <div className="job-employee">{job.employee_name}</div>}
                      <div
                        className="job-resize-handle job-resize-handle--bottom"
                        onPointerDown={(e) => startDrag(e, job, "resize-end")}
                        onPointerMove={handleDragPointerMove}
                        onPointerUp={handleDragPointerUp}
                        onPointerCancel={handleDragPointerUp}
                      />
                    </div>
                  );
                })}
              </div>
            )),
          )}
        </div>
      </div>

      {dragState?.hasMoved && dragState.kind === "move" && (
        <div
          className="job planner-job-ghost"
          style={{
            position: "fixed",
            left: dragState.clientX - dragState.grabPxX,
            top: dragState.clientY - dragState.grabPxY,
            right: "auto",
            width: dragState.cardWidth,
            height: dragState.cardHeight,
            pointerEvents: "none",
          }}
        >
          <div className="job-title">{dragState.job.work_order_number ?? "Без ЗН"}</div>
          {dragState.job.car_description && <div className="job-sub">{dragState.job.car_description}</div>}
          {dragState.job.work_description && <div className="job-work">{dragState.job.work_description}</div>}
          {dragState.job.employee_name && <div className="job-employee">{dragState.job.employee_name}</div>}
        </div>
      )}

      <WorkshopJobDialog
        key={dialogDraft?.jobId ?? `new-${dialogDraft?.jobDate}-${dialogDraft?.postNumber}-${dialogDraft?.startTime}`}
        open={dialogOpen}
        draft={dialogDraft}
        postsCount={workshop.posts_count}
        statuses={statuses}
        employees={employees}
        workshopId={workshop.id}
        workshopStartTime={workshop.start_time}
        workshopEndTime={workshop.end_time}
        fivesystemsApiEnabled={fivesystemsApiEnabled}
        onClose={closeDialog}
        onSave={save}
        onDelete={remove}
      />
    </div>
  );
}
