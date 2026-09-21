import { PlannerShell } from "@/components/planner/PlannerShell";
import { getOrgDepartments, getSlesarkaStatuses, getWorkshops } from "@/lib/backend-api";
import { getCurrentUser } from "@/lib/session";

// Must never be statically prerendered - same reasoning as every other
// data-backed page here (see app/work-orders/page.tsx).
export const dynamic = "force-dynamic";

export default async function PlannerPage() {
  let error: string | null = null;
  let departments, workshops, statuses;

  try {
    [departments, workshops, statuses] = await Promise.all([
      getOrgDepartments(),
      getWorkshops(),
      getSlesarkaStatuses(),
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  const user = await getCurrentUser();

  return (
    <div className="full-width-page">
      <h1>Планировщик</h1>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {departments && workshops && statuses && (
        <PlannerShell
          departments={departments}
          workshops={workshops}
          statuses={statuses}
          defaultDepartmentId={user?.departmentId ?? null}
          defaultWorkshopId={user?.workshopId ?? null}
        />
      )}
    </div>
  );
}
