"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { BodyCar, BodyCarStage, BodyCarWrite, Workshop } from "@/lib/backend-api";
import { bodyCarsApi } from "@/lib/planner-client";
import { CAR_STATUSES } from "@/lib/planner-constants";
import { addDaysIso, diffDaysIso, formatShortDate, formatShortDay, todayIso } from "@/lib/planner-time";

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
const CAR_COL_WIDTH = 93;

function carSpan(car: BodyCar): { start: string; end: string } | null {
  if (car.stages.length === 0) return null;
  return {
    start: car.stages.reduce((min, s) => (s.start_date < min ? s.start_date : min), car.stages[0].start_date),
    end: car.stages.reduce((max, s) => (s.end_date > max ? s.end_date : max), car.stages[0].end_date),
  };
}

function carMatches(car: BodyCar, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [car.work_order_number, car.car_description, car.vin].filter(Boolean).some((f) => f!.toLowerCase().includes(q));
}

export function BodyView({ workshop }: { workshop: Workshop }) {
  const [currentDate, setCurrentDate] = useState(todayIso());
  const [daysCount, setDaysCount] = useState<(typeof DAYS_OPTIONS)[number]>(7);
  const [search, setSearch] = useState("");
  const [cars, setCars] = useState<BodyCar[]>([]);
  const [loading, setLoading] = useState(false);
  const [dialogDraft, setDialogDraft] = useState<CarDraft | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  // Dragging a tick mark shifts a date: "boundary" (between two этапы,
  // boundaryIndex = the earlier stage's index) moves that shared date and
  // cascades every later stage by the same delta; "start"/"end" instead
  // move just the very first stage's start or the very last stage's end,
  // with nothing to cascade (see computeDraggedStages). `stageDrag` is
  // the gesture in progress, `previewStages` is that one car's stage list
  // re-dated live while dragging, swapped in for rendering only
  // (committed to the server on mouseup); everything else keeps reading
  // from `cars`.
  const [stageDrag, setStageDrag] = useState<{
    carId: string;
    kind: "boundary" | "start" | "end";
    boundaryIndex: number;
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
    setLoading(true);
    bodyCarsApi
      .list(workshop.id)
      .then(setCars)
      .catch(() => setCars([]))
      .finally(() => setLoading(false));
  };

  useEffect(reload, [workshop.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const visibleCars = cars.filter((car) => {
    const span = carSpan(car);
    if (!span) return true;
    return span.start <= windowEnd && span.end >= windowStart;
  });

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
    setDialogOpen(false);
    reload();
  };

  const remove = async () => {
    if (dialogDraft?.carId) await bodyCarsApi.remove(dialogDraft.carId);
    setDialogOpen(false);
    reload();
  };

  const changeStatus = async (car: BodyCar, status: string) => {
    await bodyCarsApi.update(car.id, {
      work_order_id: car.work_order_id,
      car_description: car.car_description,
      vin: car.vin,
      plate: car.plate,
      client_name: car.client_name,
      work_description: car.work_description,
      status,
      stages: car.stages.map((s) => ({ stage_name: s.stage_name, note: s.note, start_date: s.start_date, end_date: s.end_date })),
    });
    reload();
  };

  const computeDraggedStages = (deltaDays: number): BodyCarStage[] => {
    if (!stageDrag) return [];
    const { kind, boundaryIndex, originalStages } = stageDrag;

    if (kind === "start") {
      const first = originalStages[0];
      let newStart = addDaysIso(first.start_date, deltaDays);
      if (newStart > first.end_date) newStart = first.end_date; // can't push past its own end
      return originalStages.map((stage, i) => (i === 0 ? { ...stage, start_date: newStart } : stage));
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

  useEffect(() => {
    if (!stageDrag) return;

    const onMove = (e: MouseEvent) => {
      const deltaDays = Math.round((e.clientX - stageDrag.startMouseX) / DAY_WIDTH);
      setPreviewStages({ carId: stageDrag.carId, stages: computeDraggedStages(deltaDays) });
    };

    const onUp = async (e: MouseEvent) => {
      const deltaDays = Math.round((e.clientX - stageDrag.startMouseX) / DAY_WIDTH);
      const carId = stageDrag.carId;
      setStageDrag(null);
      if (deltaDays === 0) {
        setPreviewStages(null);
        return;
      }
      justDraggedRef.current = true;
      setTimeout(() => {
        justDraggedRef.current = false;
      }, 50);
      const finalStages = computeDraggedStages(deltaDays);
      const car = cars.find((c) => c.id === carId);
      if (car) {
        await bodyCarsApi.update(carId, {
          work_order_id: car.work_order_id,
          car_description: car.car_description,
          vin: car.vin,
          plate: car.plate,
          client_name: car.client_name,
          work_description: car.work_description,
          status: car.status,
          stages: finalStages.map((s) => ({ stage_name: s.stage_name, note: s.note, start_date: s.start_date, end_date: s.end_date })),
        });
        reload();
      }
      setPreviewStages(null);
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stageDrag]);

  const stagesFor = (car: BodyCar): BodyCarStage[] =>
    previewStages && previewStages.carId === car.id ? previewStages.stages : car.stages;

  const todayStr = todayIso();
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
          <input type="date" value={currentDate} onChange={(e) => e.target.value && setCurrentDate(e.target.value)} />
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

      {loading && <p className="admin-hint">Загрузка…</p>}

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
              const span = carSpan(car);
              const dim = search.trim() && !carMatches(car, search);
              return (
                <tr key={car.id} className={dim ? "planner-job-dim" : ""} style={{ borderLeft: `7px solid ${car.color}` }}>
                  <td className="carc" onClick={() => openEdit(car)}>
                    <div className="l1">
                      <span className="order">{car.work_order_number ?? "—"}</span>
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
                      style={{ width: tableWidth, height: 40 }}
                      onClick={() => {
                        if (justDraggedRef.current) return;
                        openEdit(car);
                      }}
                    >
                      {stagesFor(car).map((stage, index, stages) => {
                        const left = diffDaysIso(windowStart, stage.start_date) * DAY_WIDTH;
                        const width = (diffDaysIso(stage.start_date, stage.end_date) + 1) * DAY_WIDTH - 2;
                        const hasNext = index < stages.length - 1;
                        const isFirst = index === 0;
                        const isLast = index === stages.length - 1;
                        // Clamp to the visible window on both sides, not
                        // just the left edge - otherwise a segment/handle
                        // for a scrolled-off day still draws a sliver at
                        // (or past) the grid's edge instead of disappearing.
                        const clampedLeft = Math.max(left, 0);
                        const clampedWidth = Math.min(left + width, tableWidth) - clampedLeft;
                        const boundaryX = left + width;
                        const startHandleVisible = left >= 0 && left <= tableWidth;
                        const boundaryHandleVisible = boundaryX >= 0 && boundaryX <= tableWidth;
                        return (
                          <div key={stage.id}>
                            {clampedWidth > 0 && (
                              <div
                                className="planner-body-segment"
                                style={{ left: clampedLeft, width: clampedWidth, background: car.color }}
                                title={`${stage.stage_name}${stage.note ? " · " + stage.note : ""}`}
                              >
                                {stage.stage_name}
                              </div>
                            )}
                            {/* Торцевые ручки - край самого первого и самого
                                последнего этапа тоже можно тянуть, не
                                только границы между этапами. Each is
                                guarded the same way as the segment above,
                                so a handle for a day outside the visible
                                window disappears with it. */}
                            {isFirst && startHandleVisible && (
                              <div
                                className="planner-body-boundary"
                                style={{ left }}
                                onMouseDown={(e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  setStageDrag({
                                    carId: car.id,
                                    kind: "start",
                                    boundaryIndex: -1,
                                    startMouseX: e.clientX,
                                    originalStages: car.stages,
                                  });
                                }}
                              />
                            )}
                            {hasNext && boundaryHandleVisible && (
                              <div
                                className="planner-body-boundary"
                                style={{ left: boundaryX }}
                                onMouseDown={(e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  setStageDrag({
                                    carId: car.id,
                                    kind: "boundary",
                                    boundaryIndex: index,
                                    startMouseX: e.clientX,
                                    originalStages: car.stages,
                                  });
                                }}
                              />
                            )}
                            {isLast && boundaryHandleVisible && (
                              <div
                                className="planner-body-boundary"
                                style={{ left: boundaryX }}
                                onMouseDown={(e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  setStageDrag({
                                    carId: car.id,
                                    kind: "end",
                                    boundaryIndex: index,
                                    startMouseX: e.clientX,
                                    originalStages: car.stages,
                                  });
                                }}
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
        onClose={closeDialog}
        onSave={save}
        onDelete={remove}
      />
    </div>
  );
}
