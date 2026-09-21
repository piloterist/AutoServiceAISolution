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

type ViewSpan = 1 | 3 | 7;

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
  // Which job is mid-drag + how far below its own top edge it was grabbed
  // (so dropping preserves that same grab point instead of snapping the
  // card's top edge to the cursor) - a ref, not state, since it changes on
  // every mousemove-driven dragover and must never trigger a re-render.
  const dragRef = useRef<{ job: WorkshopJob; grabOffsetMinutes: number } | null>(null);

  const days = useMemo(
    () => Array.from({ length: viewSpan }, (_, i) => addDaysIso(currentDate, i)),
    [currentDate, viewSpan],
  );

  const statusById = useMemo(() => new Map(statuses.map((s) => [s.id, s])), [statuses]);

  const slots = useMemo(() => {
    const start = timeToMinutes(workshop.start_time);
    const end = timeToMinutes(workshop.end_time);
    const out: number[] = [];
    for (let m = start; m < end; m += SLOT_MINUTES) out.push(m);
    return out;
  }, [workshop.start_time, workshop.end_time]);

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

  const handleDragStart = (e: React.DragEvent, job: WorkshopJob) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const grabOffsetMinutes = roundToSlot(((e.clientY - rect.top) / SLOT_HEIGHT) * SLOT_MINUTES, SLOT_MINUTES);
    dragRef.current = { job, grabOffsetMinutes };
    e.dataTransfer.effectAllowed = "move";
  };

  const handleDrop = async (e: React.DragEvent, day: string, post: number) => {
    e.preventDefault();
    const dragging = dragRef.current;
    dragRef.current = null;
    if (!dragging) return;

    const rect = e.currentTarget.getBoundingClientRect();
    const pointerMinutes = ((e.clientY - rect.top) / SLOT_HEIGHT) * SLOT_MINUTES;
    const duration = timeToMinutes(dragging.job.end_time) - timeToMinutes(dragging.job.start_time);
    let start = roundToSlot(dayStartMinutes + pointerMinutes - dragging.grabOffsetMinutes, SLOT_MINUTES);
    start = Math.max(dayStartMinutes, Math.min(start, dayEndMinutes - duration));

    try {
      await workshopJobsApi.update(dragging.job.id, {
        work_order_id: dragging.job.work_order_id,
        car_description: dragging.job.car_description,
        vin: dragging.job.vin,
        plate: dragging.job.plate,
        client_name: dragging.job.client_name,
        work_description: dragging.job.work_description,
        job_date: day,
        post_number: post,
        start_time: `${minutesToTime(start)}:00`,
        end_time: `${minutesToTime(start + duration)}:00`,
        norm_hours: dragging.job.norm_hours,
        status_id: dragging.job.status_id,
      });
      reload();
    } catch (err) {
      setDragError(err instanceof Error ? err.message : "Не удалось перенести запись");
      setTimeout(() => setDragError(null), 3000);
    }
  };

  const colH = slots.length * SLOT_HEIGHT;
  const todayStr = todayIso();

  return (
    <div>
      <div className="toolbar">
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
                className={day === todayStr ? "col today" : "col"}
                style={{ height: colH }}
                onClick={(e) => {
                  if ((e.target as HTMLElement).closest(".job")) return;
                  const rect = e.currentTarget.getBoundingClientRect();
                  const offsetMinutes = ((e.clientY - rect.top) / SLOT_HEIGHT) * SLOT_MINUTES;
                  const start = roundToSlot(timeToMinutes(workshop.start_time) + offsetMinutes, SLOT_MINUTES);
                  openCreate(day, post, start);
                }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => handleDrop(e, day, post)}
              >
                {jobsFor(day, post).map((job) => {
                  const status = job.status_id ? statusById.get(job.status_id) : undefined;
                  const top = ((timeToMinutes(job.start_time) - timeToMinutes(workshop.start_time)) / SLOT_MINUTES) * SLOT_HEIGHT;
                  const height = ((timeToMinutes(job.end_time) - timeToMinutes(job.start_time)) / SLOT_MINUTES) * SLOT_HEIGHT - 2;
                  const dim = search.trim() && !jobMatches(job, search);
                  return (
                    <div
                      key={job.id}
                      draggable
                      className={dim ? "job planner-job-dim" : "job"}
                      style={{
                        top,
                        height: Math.max(18, height),
                        background: status ? `${status.color}33` : "var(--surface2)",
                        borderLeftColor: status ? status.color : "var(--border)",
                      }}
                      onDragStart={(e) => handleDragStart(e, job)}
                      onClick={(e) => {
                        e.stopPropagation();
                        openEdit(job);
                      }}
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
