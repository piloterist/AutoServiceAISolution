"use client";

import { useMemo, useState } from "react";

import type { OrgDepartment, SlesarkaStatus, Workshop } from "@/lib/backend-api";

import { BodyView } from "./BodyView";
import { MechanicalView } from "./MechanicalView";

/** Picks the workshop a department/type switch should land on: prefers the
 * one marked "по умолчанию", otherwise the first match - see product brief
 * part 3 on Цеха.is_default. */
function pickWorkshop(workshops: Workshop[], departmentId: string, workshopType: string): Workshop | null {
  const candidates = workshops.filter((w) => w.department_id === departmentId && w.workshop_type === workshopType);
  return candidates.find((w) => w.is_default) ?? candidates[0] ?? null;
}

export function PlannerShell({
  departments,
  workshops,
  statuses,
  defaultDepartmentId,
  defaultWorkshopId,
}: {
  departments: OrgDepartment[];
  workshops: Workshop[];
  statuses: SlesarkaStatus[];
  defaultDepartmentId: string | null;
  defaultWorkshopId: string | null;
}) {
  const initialWorkshop = defaultWorkshopId ? workshops.find((w) => w.id === defaultWorkshopId) : undefined;
  const initialDepartmentId =
    initialWorkshop?.department_id ??
    (defaultDepartmentId && departments.some((d) => d.id === defaultDepartmentId)
      ? defaultDepartmentId
      : departments[0]?.id ?? null);

  const [departmentId, setDepartmentId] = useState<string | null>(initialDepartmentId);
  const [workshopId, setWorkshopId] = useState<string | null>(
    initialWorkshop?.id ??
      (initialDepartmentId
        ? (pickWorkshop(workshops, initialDepartmentId, "Слесарный") ??
          pickWorkshop(workshops, initialDepartmentId, "Кузовной"))?.id ?? null
        : null),
  );

  const departmentWorkshopTypes = useMemo(() => {
    if (!departmentId) return [];
    const types = new Set(workshops.filter((w) => w.department_id === departmentId).map((w) => w.workshop_type));
    return Array.from(types);
  }, [workshops, departmentId]);

  const selectedWorkshop = workshops.find((w) => w.id === workshopId) ?? null;

  const selectDepartment = (id: string) => {
    setDepartmentId(id);
    const preferred =
      pickWorkshop(workshops, id, "Слесарный") ?? pickWorkshop(workshops, id, "Кузовной") ?? null;
    setWorkshopId(preferred?.id ?? null);
  };

  const selectWorkshopType = (type: string) => {
    if (!departmentId) return;
    const workshop = pickWorkshop(workshops, departmentId, type);
    setWorkshopId(workshop?.id ?? null);
  };

  if (departments.length === 0) {
    return (
      <div>
        <h1 className="planner-title">Планировщик</h1>
        <div className="card">
          <p>Сначала добавьте подразделение и цех в Настройках.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="planner-flex-col">
      {/* "Планировщик" + переключатель подразделений на одной строке;
          цеха - отдельной строкой ниже (список цехов относится к уже
          выбранному подразделению, смешивать с ним в одну строку было
          лишним). */}
      <div className="planner-header">
        <h1 className="planner-title">Планировщик</h1>
        <div className="planner-dept-switch">
          {departments.map((department) => (
            <button
              key={department.id}
              type="button"
              className={department.id === departmentId ? "planner-dept-btn planner-dept-btn--on" : "planner-dept-btn"}
              onClick={() => selectDepartment(department.id)}
            >
              {department.name}
            </button>
          ))}
        </div>
      </div>

      {departmentWorkshopTypes.length > 0 && (
        <div className="admin-tabs planner-workshop-type-tabs">
          {departmentWorkshopTypes.map((type) => (
            <button
              key={type}
              type="button"
              className={selectedWorkshop?.workshop_type === type ? "admin-tab admin-tab--on" : "admin-tab"}
              onClick={() => selectWorkshopType(type)}
            >
              {type}
            </button>
          ))}
        </div>
      )}

      {!selectedWorkshop && (
        <div className="card">
          <p>В этом подразделении пока нет цехов. Добавьте их в Настройках.</p>
        </div>
      )}

      {selectedWorkshop && selectedWorkshop.workshop_type === "Слесарный" && (
        <MechanicalView workshop={selectedWorkshop} statuses={statuses} />
      )}
      {selectedWorkshop && selectedWorkshop.workshop_type === "Кузовной" && <BodyView workshop={selectedWorkshop} />}
    </div>
  );
}
