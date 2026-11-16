"use client";

import { BodyCarDialog, emptyCarDraft } from "@/components/planner/BodyCarDialog";
import { emptyJobDraft, WorkshopJobDialog } from "@/components/planner/WorkshopJobDialog";
import { formatPhone } from "@/components/crm/columns";
import type { CrmTask, Employee, SlesarkaStatus, Workshop } from "@/lib/backend-api";
import { bodyCarsApi, workshopJobsApi } from "@/lib/planner-client";
import { minutesToTime, timeToMinutes, todayIso } from "@/lib/planner-time";

/** «Записан на осмотр» руками (product ask, 2026-11-16): карточку из «На контроле» перетащили в
 * этот столбец - открывается та же форма записи, что в планировщике цеха карточки (кузовной -
 * машина с этапами, слесарный - запись на пост). После сохранения запись создаётся в планировщике,
 * а карточка переезжает в «Записан на осмотр», связанная с ней: возврат в «На контроле» запись
 * удалит, «Отказ» оставит. */
export function InspectionBookingDialog({
  task,
  workshop,
  employees,
  statuses,
  fivesystemsApiEnabled,
  onClose,
  onMove,
}: {
  task: CrmTask | null;
  workshop: Workshop | null;
  employees: Employee[];
  statuses: SlesarkaStatus[];
  fivesystemsApiEnabled: boolean;
  onClose: () => void;
  /** Moves the card to «Записан на осмотр» with the created record; null = done, else the error. */
  onMove: (task: CrmTask, link: { body_car_id?: string; workshop_job_id?: string }) => Promise<string | null>;
}) {
  if (!task || !workshop) return null;

  if (workshop.workshop_type === "Кузовной") {
    const draft = {
      ...emptyCarDraft(todayIso()),
      status: "Ожидание",
      phone: formatPhone(task.phone),
      clientName: task.client_name ?? "",
      carDescription: task.car_description ?? "",
    };
    return (
      <BodyCarDialog
        key={task.id}
        open
        draft={draft}
        employees={employees}
        workshopId={workshop.id}
        fivesystemsApiEnabled={fivesystemsApiEnabled}
        onClose={onClose}
        onSave={async (write) => {
          const car = await bodyCarsApi.create(workshop.id, write);
          const failure = await onMove(task, { body_car_id: car.id });
          if (failure) {
            await bodyCarsApi.remove(car.id).catch(() => undefined);
            throw new Error(failure);
          }
        }}
        onDelete={async () => undefined}
      />
    );
  }

  const start = minutesToTime(timeToMinutes(workshop.start_time));
  const end = minutesToTime(Math.min(timeToMinutes(start) + 30, timeToMinutes(workshop.end_time)));
  const draft = {
    ...emptyJobDraft(todayIso(), 1, start, end, statuses),
    statusId: statuses.find((s) => s.name === "Ожидание")?.id ?? statuses.find((s) => s.name === "Запись")?.id ?? null,
    phone: formatPhone(task.phone),
    clientName: task.client_name ?? "",
    carDescription: task.car_description ?? "",
  };
  return (
    <WorkshopJobDialog
      key={task.id}
      open
      draft={draft}
      postsCount={workshop.posts_count}
      statuses={statuses}
      employees={employees}
      workshopId={workshop.id}
      workshopStartTime={minutesToTime(timeToMinutes(workshop.start_time))}
      workshopEndTime={minutesToTime(timeToMinutes(workshop.end_time))}
      fivesystemsApiEnabled={fivesystemsApiEnabled}
      onClose={onClose}
      onSave={async (write) => {
        const job = await workshopJobsApi.create(workshop.id, write);
        const failure = await onMove(task, { workshop_job_id: job.id });
        if (failure) {
          await workshopJobsApi.remove(job.id).catch(() => undefined);
          throw new Error(failure);
        }
      }}
      onDelete={async () => undefined}
    />
  );
}
