"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { SlesarkaStatus, Workshop, WorkshopJob, WorkshopJobWrite } from "@/lib/backend-api";
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

type DragState = {
  job: WorkshopJob;
  pointerId: number;
  grabOffsetMinutes: number;
  // Pixel offset from the card's own top-left corner to where it was
  // grabbed, so the ghost tracks the cursor at the same point instead of
  // snapping its corner to it.
  grabPxX: number;
  grabPxY: number;
  cardWidth: number;
  cardHeight: number;
  clientX: number;
  clientY: number;
  hasMoved: boolean;
  // Re-resolved on every pointermove (see the drag effect below) instead
  // of only once at drop - a single elementFromPoint() read exactly at
  // pointerup proved unreliable (post/day silently failed to update while
  // time did), so the last-known-good column found while actually moving
  // is what gets committed.
  targetDay: string | null;
  targetPost: number | null;
};

function money(amount: string | number | null | undefined): string {
  const n = typeof amount === "string" ? Number(amount) : (amount ?? 0);
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(n || 0);
}

function jobMatches(job: WorkshopJob, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [job.work_order_number, job.car_description, job.vin]
    .filter(Boolean)
    .some((field) => field!.toLowerCase().includes(q));
}

export function MechanicalView({ workshop, statuses }: { workshop: Workshop; statuses: SlesarkaStatus[] }) {
  const [viewSpan, setViewSpan] = useState<ViewSpan>(1);
  const [currentDate, setCurrentDate] = useState(todayIso());
  const [search, setSearch] = useState("");
  const [jobs, setJobs] = useState<WorkshopJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [dialogDraft, setDialogDraft] = useState<JobDraft | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dragError, setDragError] = useState<string | null>(null);
  // Pointer-events-based drag (not native HTML5 DnD - that API's drop
  // target resolution turned out unreliable over the per-slot cells added
  // for :hover, and its ghost image jumping around read as "форма прыгает"
  // with no visible confirmation the move actually landed). `dragState` is
  // real state so the ghost re-renders every move; `dragStateRef` mirrors
  // it so the window-level listeners (attached once per drag) always read
  // the latest values instead of a stale closure.
  const [dragState, setDragState] = useState<DragState | null>(null);
  const dragStateRef = useRef<DragState | null>(null);
  const finishDragRef = useRef<(clientX: number, clientY: number) => void>(() => {});

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
    setLoading(true);
    workshopJobsApi
      .list(workshop.id, days[0], days[days.length - 1])
      .then(setJobs)
      .catch(() => setJobs([]))
      .finally(() => setLoading(false));
  };

  useEffect(reload, [workshop.id, days[0], days[days.length - 1]]); // eslint-disable-line react-hooks/exhaustive-deps

  const jobsFor = (day: string, post: number) =>
    jobs.filter((j) => j.job_date === day && j.post_number === post);

  const dayStats = (day: string) => {
    const dayJobs = jobs.filter((j) => j.job_date === day);
    const plan = dayJobs.reduce((sum, j) => sum + Number(j.amount ?? 0), 0);
    const fact = dayJobs
      .filter((j) => j.work_order_status === "Закрыт")
      .reduce((sum, j) => sum + Number(j.amount ?? 0), 0);
    const bookedMinutes = dayJobs.reduce((sum, j) => sum + (timeToMinutes(j.end_time) - timeToMinutes(j.start_time)), 0);
    const capacity = workshop.posts_count * (timeToMinutes(workshop.end_time) - timeToMinutes(workshop.start_time));
    const load = capacity > 0 ? Math.round((bookedMinutes / capacity) * 100) : 0;
    return { plan, fact, load };
  };

  const openCreate = (day: string, post: number, startMinutes: number) => {
    const start = minutesToTime(startMinutes);
    const end = minutesToTime(Math.min(startMinutes + SLOT_MINUTES, timeToMinutes(workshop.end_time)));
    setDialogDraft(emptyJobDraft(day, post, start, end));
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
    setDialogOpen(false);
    reload();
  };

  const remove = async () => {
    if (dialogDraft?.jobId) await workshopJobsApi.remove(dialogDraft.jobId);
    setDialogOpen(false);
    reload();
  };

  const dayEndMinutes = timeToMinutes(workshop.end_time);
  const dayStartMinutes = timeToMinutes(workshop.start_time);

  const startDrag = (e: React.PointerEvent, job: WorkshopJob) => {
    if (e.button !== 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const grabOffsetMinutes = roundToSlot(((e.clientY - rect.top) / SLOT_HEIGHT) * SLOT_MINUTES, SLOT_MINUTES);
    const next: DragState = {
      job,
      pointerId: e.pointerId,
      grabOffsetMinutes,
      grabPxX: e.clientX - rect.left,
      grabPxY: e.clientY - rect.top,
      cardWidth: rect.width,
      cardHeight: rect.height,
      clientX: e.clientX,
      clientY: e.clientY,
      hasMoved: false,
      targetDay: job.job_date,
      targetPost: job.post_number,
    };
    dragStateRef.current = next;
    setDragState(next);
  };

  // Always reads the latest render's `jobs`/`workshop` via this ref (kept
  // current below) so the window pointerup listener - attached once per
  // drag - never acts on stale data.
  finishDragRef.current = (clientX: number, clientY: number) => {
    const dragging = dragStateRef.current;
    dragStateRef.current = null;
    setDragState(null);
    if (!dragging) return;

    if (!dragging.hasMoved) {
      openEdit(dragging.job);
      return;
    }

    if (dragging.targetDay === null || dragging.targetPost === null) return;
    const day = dragging.targetDay;
    const post = dragging.targetPost;
    // Recompute the target column's rect fresh (not cached from an
    // earlier move) since scrolling can shift it between then and drop.
    const target = document.querySelector<HTMLElement>(`[data-planner-col][data-day="${day}"][data-post="${post}"]`);
    if (!target) return;
    const rect = target.getBoundingClientRect();
    const pointerMinutes = ((clientY - rect.top) / SLOT_HEIGHT) * SLOT_MINUTES;
    const duration = timeToMinutes(dragging.job.end_time) - timeToMinutes(dragging.job.start_time);
    let start = roundToSlot(dayStartMinutes + pointerMinutes - dragging.grabOffsetMinutes, SLOT_MINUTES);
    start = Math.max(dayStartMinutes, Math.min(start, dayEndMinutes - duration));
    const startTime = `${minutesToTime(start)}:00`;
    const endTime = `${minutesToTime(start + duration)}:00`;

    if (day === dragging.job.job_date && post === dragging.job.post_number && startTime === dragging.job.start_time) {
      return;
    }

    const write: WorkshopJobWrite = {
      work_order_id: dragging.job.work_order_id,
      car_description: dragging.job.car_description,
      vin: dragging.job.vin,
      plate: dragging.job.plate,
      client_name: dragging.job.client_name,
      work_description: dragging.job.work_description,
      job_date: day,
      post_number: post,
      start_time: startTime,
      end_time: endTime,
      norm_hours: dragging.job.norm_hours,
      status_id: dragging.job.status_id,
    };

    // Optimistic: move the card immediately instead of waiting on the
    // round trip, then reconcile with the server (or roll back on error).
    setJobs((prev) =>
      prev.map((j) => (j.id === dragging.job.id ? { ...j, job_date: day, post_number: post, start_time: startTime, end_time: endTime } : j)),
    );

    workshopJobsApi.update(dragging.job.id, write).then(reload, (err) => {
      setDragError(err instanceof Error ? err.message : "Не удалось перенести запись");
      setTimeout(() => setDragError(null), 3000);
      reload();
    });
  };

  useEffect(() => {
    if (!dragState) return;

    const handleMove = (e: PointerEvent) => {
      const current = dragStateRef.current;
      if (!current || e.pointerId !== current.pointerId) return;
      const dx = e.clientX - current.clientX;
      const dy = e.clientY - current.clientY;
      const hasMoved = current.hasMoved || Math.hypot(dx, dy) > DRAG_THRESHOLD_PX;

      // Re-resolve the column under the cursor on every move (not just
      // once at drop) and keep the ghost hidden from hit-testing while
      // doing it, so the drop always uses a column that was genuinely
      // under the cursor at some point during the gesture.
      let targetDay = current.targetDay;
      let targetPost = current.targetPost;
      if (hasMoved) {
        const el = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-planner-col]");
        if (el?.dataset.day && el.dataset.post) {
          targetDay = el.dataset.day;
          targetPost = Number(el.dataset.post);
        }
      }

      const next = { ...current, clientX: e.clientX, clientY: e.clientY, hasMoved, targetDay, targetPost };
      dragStateRef.current = next;
      setDragState(next);
    };
    const handleUp = (e: PointerEvent) => {
      if (e.pointerId !== dragStateRef.current?.pointerId) return;
      finishDragRef.current(e.clientX, e.clientY);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("pointercancel", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("pointercancel", handleUp);
    };
    // Re-subscribes only when a drag starts/ends, not on every move.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragState !== null]);

  const colH = slots.length * SLOT_HEIGHT;
  const todayStr = todayIso();

  return (
    <div className="planner-flex-col">
      <div className="planner-toolbar">
        <div className="grp">
          <button type="button" onClick={() => setCurrentDate(addDaysIso(currentDate, -viewSpan))}>
            ‹
          </button>
          <button type="button" onClick={() => setCurrentDate(todayStr)}>
            Сегодня
          </button>
          <button type="button" onClick={() => setCurrentDate(addDaysIso(currentDate, viewSpan))}>
            ›
          </button>
          <input type="date" value={currentDate} onChange={(e) => e.target.value && setCurrentDate(e.target.value)} />
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

      {loading && <p className="admin-hint">Загрузка…</p>}
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
                  <span>
                    План <b>{money(stats.plan)} ₽</b>
                  </span>
                  <span>
                    Факт <b style={{ color: "var(--ok)" }}>{money(stats.fact)} ₽</b>
                  </span>
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
                data-planner-col
                data-day={day}
                data-post={post}
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
                  const top = ((timeToMinutes(job.start_time) - timeToMinutes(workshop.start_time)) / SLOT_MINUTES) * SLOT_HEIGHT;
                  const height = ((timeToMinutes(job.end_time) - timeToMinutes(job.start_time)) / SLOT_MINUTES) * SLOT_HEIGHT - 2;
                  const dim = search.trim() && !jobMatches(job, search);
                  const isDragSource = dragState?.hasMoved && dragState.job.id === job.id;
                  return (
                    <div
                      key={job.id}
                      className={[dim ? "job planner-job-dim" : "job", isDragSource ? "planner-job-drag-source" : ""]
                        .filter(Boolean)
                        .join(" ")}
                      style={{
                        top,
                        height: Math.max(18, height),
                        background: status ? `${status.color}33` : "var(--surface2)",
                        borderLeftColor: status ? status.color : "var(--border)",
                        touchAction: "none",
                        // Once dragging, this card is just a dimmed marker
                        // of the origin - it must not intercept
                        // elementFromPoint() lookups for the column under
                        // the cursor (see handleMove).
                        pointerEvents: isDragSource ? "none" : undefined,
                      }}
                      onPointerDown={(e) => startDrag(e, job)}
                    >
                      <div className="job-title">{job.work_order_number ?? "Без ЗН"}</div>
                      {job.car_description && <div className="job-sub">{job.car_description}</div>}
                      {job.work_description && <div className="job-work">{job.work_description}</div>}
                    </div>
                  );
                })}
              </div>
            )),
          )}
        </div>
      </div>

      {dragState?.hasMoved && (
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
        </div>
      )}

      <WorkshopJobDialog
        key={dialogDraft?.jobId ?? `new-${dialogDraft?.jobDate}-${dialogDraft?.postNumber}-${dialogDraft?.startTime}`}
        open={dialogOpen}
        draft={dialogDraft}
        postsCount={workshop.posts_count}
        statuses={statuses}
        workshopStartTime={workshop.start_time}
        workshopEndTime={workshop.end_time}
        onClose={closeDialog}
        onSave={save}
        onDelete={remove}
      />
    </div>
  );
}
