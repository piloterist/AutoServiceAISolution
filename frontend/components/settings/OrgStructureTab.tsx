"use client";

import type { OrgDepartment, SlesarkaStatus, Workshop, WorkshopSourceDepartment } from "@/lib/backend-api";

import { DepartmentsTab } from "./DepartmentsTab";
import { SlesarkaStatusesTab } from "./SlesarkaStatusesTab";
import { WorkshopSourceDepartmentsTab } from "./WorkshopSourceDepartmentsTab";
import { WorkshopsTab } from "./WorkshopsTab";

/** Merges the four previously separate tabs that together describe how the
 * org/1C data maps onto the product (product ask, 2026-10-14: "объедини в
 * одну закладку Орг. структура") into ONE shared card, laid out as a
 * precise 3-column grid per the exact spec given, 2026-10-14:
 *
 *   [Подразделения] [Статусы слесарки] [Цеха            ]
 *   [   (cont.)    ] [    (cont.)     ] [Соответствие 1С ]
 *
 * Подразделения/Статусы слесарки each span both rows (see
 * .org-structure-span in globals.css: `grid-row: span 2`), so their height
 * always matches Цеха+Соответствие 1С's combined height automatically -
 * "при увеличении их высот - увеличиваются высоты подразделений и статусов,
 * чтобы всё было взаимосвязано" is just how CSS Grid row tracks work once
 * two cells share them, no manual height sync needed. Цеха/Соответствие 1С
 * share the grid's third (1fr) column, so they're always the same width
 * and reach the right edge ("одинаковые по ширине, до конца вправо").
 *
 * DOM order matters here - CSS Grid's auto-placement is what actually
 * produces this exact arrangement (see .org-structure-grid's
 * grid-template-columns): Подразделения and Статусы слесарки (each
 * row-span 2) claim columns 1 and 2 for both rows, leaving only column 3
 * open in row 1 for Цеха and in row 2 for Соответствие 1С. */
export function OrgStructureTab({
  departments,
  workshops,
  sourceDepartments,
  unmappedSourceDepartments,
  statuses,
}: {
  departments: OrgDepartment[];
  workshops: Workshop[];
  sourceDepartments: WorkshopSourceDepartment[];
  unmappedSourceDepartments: string[];
  statuses: SlesarkaStatus[];
}) {
  return (
    <div className="card org-structure-grid">
      <div className="org-structure-span">
        <DepartmentsTab initialDepartments={departments} />
      </div>
      <div className="org-structure-span">
        <SlesarkaStatusesTab initialStatuses={statuses} />
      </div>
      <WorkshopsTab initialWorkshops={workshops} departments={departments} />
      <WorkshopSourceDepartmentsTab
        initialRows={sourceDepartments}
        initialUnmapped={unmappedSourceDepartments}
        workshops={workshops}
      />
    </div>
  );
}
