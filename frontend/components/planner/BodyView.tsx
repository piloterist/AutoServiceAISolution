"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { DateInput } from "@/components/DateInput";
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
const CAR_COL_WIDTH = 419;

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
  const [daysCount, setDaysCount] = useState<(typeof DAYS_OPTIONS)[number]>(21);
  const [search, setSearch] = useState("");
  const [cars, setCars] = useState<BodyCar[]>([]);
  const [loading, setLoading] = useState(false);
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

  // A plain client-side reload() (re-fetch + setCars) reliably left the
  // graph showing the pre-write state until the operator refreshed the
  // browser themselves - true even with cache: "no-store" and a unique
  // cache-busting URL on the GET, so whatever's wrong isn't HTTP caching.
  // A full reload is the blunt but guaranteed-correct fix: it's exactly
  // the manual refresh already confirmed to always show the right data.
  const save = async (write: BodyCarWrite) => {
    if (dialogDraft?.carId) {
      await bodyCarsApi.update(dialogDraft.carId, write);
    } else {
      await bodyCarsApi.create(workshop.id, write);
    }
    window.location.reload();
  };

  const remove = async () => {
    if (dialogDraft?.carId) await bodyCarsApi.remove(dialogDraft.carId);
    window.location.reload();
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
    window.location.reload();
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
          work_description: car.work_description,
          status: car.status,
          stages: finalStages.map((s) => ({ stage_name: s.stage_name, note: s.note, start_date: s.start_date, end_date: s.end_date })),
        });
        // A plain client-side reload() here reliably left the graph
        // showing the pre-drag stage dates until the operator refreshed
        // the browser themselves - true even with cache: "no-store" and a
        // unique cache-busting URL on the GET, so whatever's wrong isn't
        // HTTP caching. A full reload is the blunt but guaranteed-correct
        // fix: it's exactly the manual refresh already confirmed to
        // always show the right data.
        window.location.reload();
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

      {loading && <p className="admin-hint">Загрузка…</p>}
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
                                onPointerDown={(e) => startStageDrag(e, car, "start", -1)}
                                onPointerMove={handleStageDragMove}
                                onPointerUp={handleStageDragUp}
                                onPointerCancel={handleStageDragUp}
                              />
                            )}
                            {hasNext && boundaryHandleVisible && (
                              <div
                                className="planner-body-boundary"
                                style={{ left: boundaryX }}
                                onPointerDown={(e) => startStageDrag(e, car, "boundary", index)}
                                onPointerMove={handleStageDragMove}
                                onPointerUp={handleStageDragUp}
                                onPointerCancel={handleStageDragUp}
                              />
                            )}
                            {isLast && boundaryHandleVisible && (
                              <div
                                className="planner-body-boundary"
                                style={{ left: boundaryX }}
                                onPointerDown={(e) => startStageDrag(e, car, "end", index)}
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
        onClose={closeDialog}
        onSave={save}
        onDelete={remove}
      />
    </div>
  );
}
