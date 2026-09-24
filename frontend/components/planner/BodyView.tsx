"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { DateInput } from "@/components/DateInput";
import type { BodyCar, BodyCarStage, BodyCarWrite, Employee, Workshop } from "@/lib/backend-api";
import { bodyCarsApi } from "@/lib/planner-client";
import { CAR_STATUS_APPROVAL, CAR_STATUSES, SPECIAL_CAR_STATUSES } from "@/lib/planner-constants";
import { addDaysIso, addMonthsIso, diffDaysIso, formatShortDate, formatShortDay, todayIso } from "@/lib/planner-time";

import { BodyCarDialog, carToDraft, emptyCarDraft, type CarDraft } from "./BodyCarDialog";

const DAY_WIDTH = 92;
const DAYS_OPTIONS = [7, 14, 21, 28, 35] as const;
// Must match .hcar/.carc's min-width/max-width in globals.css. table.bt
// needs an exact pixel width (not the earlier width:max-content;
// min-width:100%) - with table-layout:fixed, when the table's own width
// exceeds the sum of its columns' declared widths, the browser
// distributes the extra space across ALL columns proportionally,
// including this one, so on a screen wider than the content it grew (and
// grew by a different amount depending on how many day columns there
// were) instead of staying fixed.
const CAR_COL_WIDTH = 419;

function isSpecialStatus(status: string): boolean {
  return (SPECIAL_CAR_STATUSES as readonly string[]).includes(status);
}

/** Заметно бледнее обычной палитры цветов машин (BODY_CAR_COLORS на
 * бэкенде) - product ask: "не такая яркая как остальные этапы". */
function specialStatusColor(status: string): string {
  return status === CAR_STATUS_APPROVAL ? "#e5e7eb" /* светло-серый */ : "#dcfce7" /* светло-зелёный */;
}

/** Real этапы-based span - ignores the "Согласование"/"Готова к выдаче"
 * override (see carDisplaySpan below, used everywhere else - this raw
 * version exists only for merging overlapping этапы, which are irrelevant
 * for those two statuses anyway since they never render individual этапы). */
function carSpan(car: BodyCar): { start: string; end: string } | null {
  if (car.stages.length === 0) return null;
  return {
    start: car.stages.reduce((min, s) => (s.start_date < min ? s.start_date : min), car.stages[0].start_date),
    end: car.stages.reduce((max, s) => (s.end_date > max ? s.end_date : max), car.stages[0].end_date),
  };
}

/** "Согласование"/"Готова к выдаче" - shown/filtered as a flat ±3-month
 * window from created_at regardless of их actual этапы (product ask: these
 * two statuses aren't meaningfully placed on a day-by-day timeline). Every
 * other status uses the real stage-based span. */
function carDisplaySpan(car: BodyCar): { start: string; end: string } | null {
  if (isSpecialStatus(car.status)) {
    const created = car.created_at.slice(0, 10);
    return { start: addMonthsIso(created, -3), end: addMonthsIso(created, 3) };
  }
  return carSpan(car);
}

function hasStageOn(car: BodyCar, day: string): boolean {
  return car.stages.some((s) => s.start_date <= day && s.end_date >= day);
}

/** Список машин в цеху, сверху вниз:
 *  1. "Согласование"/"Готова к выдаче" - ВСЕГДА в самом конце, независимо
 *     от этапов/дат, среди них - от самой ранней даты создания записи.
 *  2. Остальные статусы: сначала те, у кого есть этап на сегодня (среди
 *     них - от самой ранней даты создания), затем остальные (от самой
 *     поздней даты создания) - "сегодня" всегда реальное сегодня, не
 *     `currentDate`, который можно перелистнуть. */
function compareCars(a: BodyCar, b: BodyCar, today: string): number {
  const aSpecial = isSpecialStatus(a.status);
  const bSpecial = isSpecialStatus(b.status);
  if (aSpecial !== bSpecial) return aSpecial ? 1 : -1;
  if (aSpecial && bSpecial) return a.created_at.localeCompare(b.created_at);

  const aToday = hasStageOn(a, today);
  const bToday = hasStageOn(b, today);
  if (aToday !== bToday) return aToday ? -1 : 1;
  return aToday
    ? a.created_at.localeCompare(b.created_at) // раньше созданные - выше
    : b.created_at.localeCompare(a.created_at); // позже созданные - выше
}

type StageGroup = {
  stages: BodyCarStage[];
  firstIndex: number;
  lastIndex: number;
  start: string;
  end: string;
  label: string;
  employeeName: string | null;
};

/** Соседние этапы, чьи периоды совпадают или пересекаются (не просто
 * идут вплотную день-в-день - это обычный порядок по умолчанию),
 * схлопываются в одну визуальную полоску с названиями через "/" (product
 * ask). Не трогает сами данные этапов - только то, как они рисуются. */
function groupOverlappingStages(stages: BodyCarStage[]): StageGroup[] {
  const groups: StageGroup[] = [];
  stages.forEach((stage, i) => {
    const last = groups[groups.length - 1];
    if (last && stage.start_date <= last.end) {
      last.stages.push(stage);
      last.lastIndex = i;
      if (stage.end_date > last.end) last.end = stage.end_date;
      last.label = `${last.label}/${stage.stage_name}`;
      if (!last.employeeName && stage.employee_name) last.employeeName = stage.employee_name;
    } else {
      groups.push({
        stages: [stage],
        firstIndex: i,
        lastIndex: i,
        start: stage.start_date,
        end: stage.end_date,
        label: stage.stage_name,
        employeeName: stage.employee_name,
      });
    }
  });
  return groups;
}

function carMatches(car: BodyCar, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [car.work_order_number, car.car_description, car.vin].filter(Boolean).some((f) => f!.toLowerCase().includes(q));
}

/** Wraps BodyViewInner and forces a full remount of it (fresh state,
 * fresh useEffect, fresh fetch) after every write, by bumping `key` - see
 * the identical wrapper on MechanicalView for the full reasoning. */
export function BodyView(props: { workshop: Workshop; employees: Employee[]; fivesystemsApiEnabled: boolean }) {
  const [instanceKey, setInstanceKey] = useState(0);
  return <BodyViewInner key={instanceKey} {...props} onWritten={() => setInstanceKey((k) => k + 1)} />;
}

function BodyViewInner({
  workshop,
  employees,
  fivesystemsApiEnabled,
  onWritten,
}: {
  workshop: Workshop;
  employees: Employee[];
  fivesystemsApiEnabled: boolean;
  onWritten: () => void;
}) {
  const [currentDate, setCurrentDate] = useState(todayIso());
  const [daysCount, setDaysCount] = useState<(typeof DAYS_OPTIONS)[number]>(21);
  const [search, setSearch] = useState("");
  const [cars, setCars] = useState<BodyCar[]>([]);
  const [dialogDraft, setDialogDraft] = useState<CarDraft | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [stageDragError, setStageDragError] = useState<string | null>(null);

  // Dragging a tick mark shifts a date: "boundary" (between two этапы,
  // boundaryIndex = the earlier stage's index) moves that shared date and
  // cascades every later stage by the same delta; "start"/"end" instead
  // move just the very first stage's start or the very last stage's end,
  // with nothing to cascade (see computeDraggedStages). `stageDrag` is
  // the gesture in progress, `previewStages` is that one car's stage list
  // re-dated live while dragging, swapped in for rendering only
  // (committed to the server on pointerup); everything else keeps reading
  // from `cars`.
  //
  // Uses setPointerCapture on the handle that received pointerdown, with
  // onPointerMove/onPointerUp as ordinary props on that same element -
  // not document-level addEventListener wired up through a useEffect
  // keyed on stageDrag (the same fix already applied to Слесарный's own
  // drag, which stopped working reliably on repeat gestures under that
  // pattern). Pointer capture guarantees events keep reaching this
  // element regardless of where the cursor moves, so there's no
  // subscribe/cleanup lifecycle to get wrong between gestures.
  const [stageDrag, setStageDrag] = useState<{
    carId: string;
    kind: "boundary" | "start" | "end";
    boundaryIndex: number;
    pointerId: number;
    startMouseX: number;
    originalStages: BodyCarStage[];
  } | null>(null);
  const [previewStages, setPreviewStages] = useState<{ carId: string; stages: BodyCarStage[] } | null>(null);
  // A drag ends with a mouseup over the same .planner-body-bar-area that
  // also opens the edit dialog on click - the browser fires a click right
  // after, which without this would pop the dialog open on every drag.
  const justDraggedRef = useRef(false);

  const days = useMemo(() => Array.from({ length: daysCount }, (_, i) => addDaysIso(currentDate, i)), [currentDate, daysCount]);
  const windowStart = days[0];
  const windowEnd = days[days.length - 1];

  const reload = () => {
    bodyCarsApi
      .list(workshop.id)
      .then(setCars)
      .catch(() => setCars([]));
  };

  useEffect(reload, [workshop.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const todayStr = todayIso();
  const hasSearch = search.trim().length > 0;
  // Обычные (попавшие в текущее окно дат) машины видны всегда; машины ВНЕ
  // окна показываются, только если сейчас идёт поиск и они ему
  // соответствуют - product ask: искать нужно по всем периодам, но сам
  // график/окно дат при этом двигать не надо.
  const visibleCars = cars
    .filter((car) => {
      const span = carDisplaySpan(car);
      const inWindow = !span || (span.start <= windowEnd && span.end >= windowStart);
      if (inWindow) return true;
      return hasSearch && carMatches(car, search);
    })
    .sort((a, b) => compareCars(a, b, todayStr));

  const openCreate = (arriveDate: string) => {
    setDialogDraft(emptyCarDraft(arriveDate));
    setDialogOpen(true);
  };
  const openEdit = (car: BodyCar) => {
    setDialogDraft(carToDraft(car));
    setDialogOpen(true);
  };
  const closeDialog = () => setDialogOpen(false);

  const save = async (write: BodyCarWrite) => {
    if (dialogDraft?.carId) {
      await bodyCarsApi.update(dialogDraft.carId, write);
    } else {
      await bodyCarsApi.create(workshop.id, write);
    }
    onWritten();
  };

  const remove = async () => {
    if (dialogDraft?.carId) await bodyCarsApi.remove(dialogDraft.carId);
    onWritten();
  };

  const changeStatus = async (car: BodyCar, status: string) => {
    await bodyCarsApi.update(car.id, {
      work_order_id: car.work_order_id,
      car_description: car.car_description,
      vin: car.vin,
      plate: car.plate,
      client_name: car.client_name,
      phone: car.phone,
      work_description: car.work_description,
      status,
      on_site: car.on_site,
      stages: car.stages.map((s) => ({
        stage_name: s.stage_name,
        note: s.note,
        start_date: s.start_date,
        end_date: s.end_date,
        employee_id: s.employee_id,
      })),
    });
    onWritten();
  };

  const computeDraggedStages = (deltaDays: number, drag: NonNullable<typeof stageDrag>): BodyCarStage[] => {
    const { kind, boundaryIndex, originalStages } = drag;

    if (kind === "start") {
      // Moving the very first stage's start is "when does the car arrive" -
      // shift every stage (including this one's own end) by the same
      // delta so the whole plan slides together, matching the dialog's
      // same-index-0 handling (BodyCarDialog's updateStageStart) instead
      // of just overlapping stage 1.
      return originalStages.map((stage) => ({
        ...stage,
        start_date: addDaysIso(stage.start_date, deltaDays),
        end_date: addDaysIso(stage.end_date, deltaDays),
      }));
    }

    if (kind === "end") {
      const lastIndex = originalStages.length - 1;
      const last = originalStages[lastIndex];
      let newEnd = addDaysIso(last.end_date, deltaDays);
      if (newEnd < last.start_date) newEnd = last.start_date; // can't push before its own start
      return originalStages.map((stage, i) => (i === lastIndex ? { ...stage, end_date: newEnd } : stage));
    }

    const before = originalStages[boundaryIndex];
    const after = originalStages[boundaryIndex + 1];
    // Can't drag the boundary earlier than the stage-before's own start -
    // product brief: "нельзя сделать раньше чем у него черточка начала".
    const minBoundary = before.start_date;
    let newBoundary = addDaysIso(after.start_date, deltaDays);
    if (newBoundary < minBoundary) newBoundary = minBoundary;
    const appliedDelta = diffDaysIso(after.start_date, newBoundary);

    return originalStages.map((stage, i) => {
      if (i === boundaryIndex) return { ...stage, end_date: addDaysIso(newBoundary, -1) };
      if (i > boundaryIndex) {
        return { ...stage, start_date: addDaysIso(stage.start_date, appliedDelta), end_date: addDaysIso(stage.end_date, appliedDelta) };
      }
      return stage;
    });
  };

  const startStageDrag = (
    e: React.PointerEvent<HTMLDivElement>,
    car: BodyCar,
    kind: "boundary" | "start" | "end",
    boundaryIndex: number,
  ) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    setStageDrag({
      carId: car.id,
      kind,
      boundaryIndex,
      pointerId: e.pointerId,
      startMouseX: e.clientX,
      originalStages: car.stages,
    });
  };

  const handleStageDragMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!stageDrag || e.pointerId !== stageDrag.pointerId) return;
    const deltaDays = Math.round((e.clientX - stageDrag.startMouseX) / DAY_WIDTH);
    setPreviewStages({ carId: stageDrag.carId, stages: computeDraggedStages(deltaDays, stageDrag) });
  };

  const handleStageDragUp = async (e: React.PointerEvent<HTMLDivElement>) => {
    if (!stageDrag || e.pointerId !== stageDrag.pointerId) return;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);

    const deltaDays = Math.round((e.clientX - stageDrag.startMouseX) / DAY_WIDTH);
    const drag = stageDrag;
    setStageDrag(null);
    if (deltaDays === 0) {
      setPreviewStages(null);
      return;
    }
    justDraggedRef.current = true;
    setTimeout(() => {
      justDraggedRef.current = false;
    }, 50);
    const finalStages = computeDraggedStages(deltaDays, drag);
    const car = cars.find((c) => c.id === drag.carId);
    if (car) {
      try {
        await bodyCarsApi.update(drag.carId, {
          work_order_id: car.work_order_id,
          car_description: car.car_description,
          vin: car.vin,
          plate: car.plate,
          client_name: car.client_name,
          phone: car.phone,
          work_description: car.work_description,
          status: car.status,
          on_site: car.on_site,
          stages: finalStages.map((s) => ({
            stage_name: s.stage_name,
            note: s.note,
            start_date: s.start_date,
            end_date: s.end_date,
            employee_id: s.employee_id,
          })),
        });
        onWritten();
        return;
      } catch (err) {
        // Without this, a rejected save (e.g. an invalid resulting order)
        // left previewStages showing the dragged-to position forever,
        // since nothing after the throwing await ever ran - the graph
        // looked moved while the saved record (and the edit dialog) never
        // changed at all.
        setStageDragError(err instanceof Error ? err.message : "Не удалось сохранить перенос этапа");
        setTimeout(() => setStageDragError(null), 4000);
      }
    }
    setPreviewStages(null);
  };

  const stagesFor = (car: BodyCar): BodyCarStage[] =>
    previewStages && previewStages.carId === car.id ? previewStages.stages : car.stages;

  const tableWidth = days.length * DAY_WIDTH;

  return (
    <div className="planner-flex-col">
      <div className="planner-toolbar">
        <div className="grp">
          <button type="button" onClick={() => setCurrentDate(addDaysIso(currentDate, -1))}>
            ‹
          </button>
          <button type="button" onClick={() => setCurrentDate(todayStr)}>
            Сегодня
          </button>
          <button type="button" onClick={() => setCurrentDate(addDaysIso(currentDate, 1))}>
            ›
          </button>
          <DateInput value={currentDate} onChange={(iso) => iso && setCurrentDate(iso)} />
        </div>
        <div className="grp">
          <select value={daysCount} onChange={(e) => setDaysCount(Number(e.target.value) as (typeof DAYS_OPTIONS)[number])}>
            {DAYS_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n} дн.
              </option>
            ))}
          </select>
        </div>
        <div className="grp planner-search-grp">
          <input type="search" placeholder="Поиск автомобиля" value={search} onChange={(e) => setSearch(e.target.value)} />
          <button type="button" onClick={() => setSearch("")}>
            Сбросить
          </button>
        </div>
        <div className="grp" style={{ marginLeft: "auto" }}>
          <button type="button" className="admin-btn admin-btn-primary" onClick={() => openCreate(currentDate)}>
            Записать
          </button>
        </div>
      </div>

      {stageDragError && <p className="admin-form-error">{stageDragError}</p>}

      <div className="tw">
        <table className="bt" style={{ width: CAR_COL_WIDTH + tableWidth }}>
          <thead>
            <tr>
              <th className="hcar">
                Список автомобилей в цеху
                <span className="cnt">{visibleCars.length} из {cars.length}</span>
              </th>
              {days.map((day) => (
                <th key={day} className={day === todayStr ? "today" : ""} style={{ width: DAY_WIDTH }}>
                  {formatShortDay(day)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleCars.map((car) => {
              const span = carDisplaySpan(car);
              const dim = search.trim() && !carMatches(car, search);
              return (
                <tr key={car.id} className={dim ? "planner-job-dim" : ""} style={{ borderLeft: `7px solid ${car.color}` }}>
                  <td className="carc" onClick={() => openEdit(car)}>
                    <div className="l1">
                      <span className="order">{car.work_order_number ?? "—"}</span>
                      <div className="stwrap">
                        <select
                          className="stsel"
                          value={car.status}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => changeStatus(car, e.target.value)}
                        >
                          {CAR_STATUSES.map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                        {car.on_site && <span className="planner-body-onsite">На территории</span>}
                      </div>
                    </div>
                    <div className="model" title={car.car_description ?? undefined}>
                      {car.car_description || "—"}
                    </div>
                    {car.work_description && <div className="dates">{car.work_description}</div>}
                    {span && (
                      <div className="dates">
                        <b>
                          {formatShortDate(span.start)} → {formatShortDate(span.end)}
                        </b>{" "}
                        · {diffDaysIso(span.start, span.end) + 1} дн.
                      </div>
                    )}
                  </td>
                  <td colSpan={days.length} style={{ padding: 0 }}>
                    <div
                      className="planner-body-bar-area"
                      // Fills the row's actual height (driven by .carc's
                      // content, which can run to 4 lines) instead of a
                      // fixed 40px - otherwise a taller .carc cell stretches
                      // the <tr> while this bar area stays short, leaving
                      // dead space at the bottom of the graph cell that
                      // makes that row's bar look shifted relative to the
                      // car-info column next to it. globals.css floors it
                      // at 40px so a short .carc doesn't shrink the bar.
                      style={{ width: tableWidth, height: "100%" }}
                      onClick={() => {
                        if (justDraggedRef.current) return;
                        openEdit(car);
                      }}
                    >
                      {isSpecialStatus(car.status)
                        ? // "Согласование"/"Готова к выдаче" - один статичный
                          // бледный отрезок на весь ±3-месячный диапазон
                          // (span уже посчитан через carDisplaySpan выше),
                          // без ручек перетаскивания - этапы тут не
                          // отслеживаются день-в-день.
                          (() => {
                            if (!span) return null;
                            const left = diffDaysIso(windowStart, span.start) * DAY_WIDTH;
                            const width = (diffDaysIso(span.start, span.end) + 1) * DAY_WIDTH - 2;
                            const clampedLeft = Math.max(left, 0);
                            const clampedWidth = Math.min(left + width, tableWidth) - clampedLeft;
                            if (clampedWidth <= 0) return null;
                            return (
                              <div
                                className="planner-body-segment"
                                style={{ left: clampedLeft, width: clampedWidth, background: specialStatusColor(car.status) }}
                                title={car.status}
                              >
                                <span className="planner-body-segment-stage">{car.status}</span>
                              </div>
                            );
                          })()
                        : groupOverlappingStages(stagesFor(car)).map((group, groupIndex, groups) => {
                            const left = diffDaysIso(windowStart, group.start) * DAY_WIDTH;
                            const width = (diffDaysIso(group.start, group.end) + 1) * DAY_WIDTH - 2;
                            const hasNextGroup = groupIndex < groups.length - 1;
                            const isFirstGroup = groupIndex === 0;
                            const isLastGroup = groupIndex === groups.length - 1;
                            // Clamp to the visible window on both sides, not
                            // just the left edge - otherwise a segment/handle
                            // for a scrolled-off day still draws a sliver at
                            // (or past) the grid's edge instead of disappearing.
                            const clampedLeft = Math.max(left, 0);
                            const clampedWidth = Math.min(left + width, tableWidth) - clampedLeft;
                            const boundaryX = left + width;
                            const startHandleVisible = left >= 0 && left <= tableWidth;
                            const boundaryHandleVisible = boundaryX >= 0 && boundaryX <= tableWidth;
                            const notes = group.stages.map((s) => s.note).filter((n): n is string => Boolean(n));
                            return (
                              <div key={group.stages[0].id}>
                                {clampedWidth > 0 && (
                                  <div
                                    className="planner-body-segment"
                                    style={{ left: clampedLeft, width: clampedWidth, background: car.color }}
                                    title={`${group.label}${notes.length ? " · " + notes.join(", ") : ""}${group.employeeName ? " · " + group.employeeName : ""}`}
                                  >
                                    <span className="planner-body-segment-stage">{group.label}</span>
                                    {group.employeeName && (
                                      <span className="planner-body-segment-employee">{group.employeeName}</span>
                                    )}
                                  </div>
                                )}
                                {/* Торцевые ручки - край самого первого и
                                    самого последнего этапа тоже можно тянуть,
                                    не только границы между слитыми группами.
                                    Each is guarded the same way as the
                                    segment above, so a handle for a day
                                    outside the visible window disappears
                                    with it. */}
                                {isFirstGroup && startHandleVisible && (
                                  <div
                                    className="planner-body-boundary"
                                    style={{ left }}
                                    onPointerDown={(e) => startStageDrag(e, car, "start", -1)}
                                    onPointerMove={handleStageDragMove}
                                    onPointerUp={handleStageDragUp}
                                    onPointerCancel={handleStageDragUp}
                                  />
                                )}
                                {hasNextGroup && boundaryHandleVisible && (
                                  <div
                                    className="planner-body-boundary"
                                    style={{ left: boundaryX }}
                                    onPointerDown={(e) => startStageDrag(e, car, "boundary", group.lastIndex)}
                                    onPointerMove={handleStageDragMove}
                                    onPointerUp={handleStageDragUp}
                                    onPointerCancel={handleStageDragUp}
                                  />
                                )}
                                {isLastGroup && boundaryHandleVisible && (
                                  <div
                                    className="planner-body-boundary"
                                    style={{ left: boundaryX }}
                                    onPointerDown={(e) => startStageDrag(e, car, "end", group.lastIndex)}
                                    onPointerMove={handleStageDragMove}
                                    onPointerUp={handleStageDragUp}
                                    onPointerCancel={handleStageDragUp}
                                  />
                                )}
                              </div>
                            );
                          })}
                    </div>
                  </td>
                </tr>
              );
            })}
            {visibleCars.length === 0 && (
              <tr>
                <td colSpan={days.length + 1} className="emptyrow">
                  Ничего не найдено
                </td>
              </tr>
            )}
            <tr className="newrow">
              <td className="carc" onClick={() => openCreate(currentDate)}>
                ＋ Новая машина — кликните, чтобы записать
              </td>
              {days.map((day) => (
                <td key={day} onClick={() => openCreate(day)} />
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      <BodyCarDialog
        key={dialogDraft?.carId ?? `new-${dialogDraft?.stages[0]?.startDate}`}
        open={dialogOpen}
        draft={dialogDraft}
        employees={employees}
        workshopId={workshop.id}
        fivesystemsApiEnabled={fivesystemsApiEnabled}
        onClose={closeDialog}
        onSave={save}
        onDelete={remove}
      />
    </div>
  );
}
