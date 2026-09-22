import { PlannerShell } from "@/components/planner/PlannerShell";
import { getAppSettings, getOrgDepartments, getSlesarkaStatuses, getWorkshops } from "@/lib/backend-api";
import { getCurrentUser } from "@/lib/session";

// Must never be statically prerendered - same reasoning as every other
// data-backed page here (see app/work-orders/page.tsx).
export const dynamic = "force-dynamic";

export default async function PlannerPage() {
  let error: string | null = null;
  let departments, workshops, statuses;
  // Defaults to "off" on a fetch failure - same fail-safe direction as the
  // rest of this feature (see fivesystems_client.py's module docstring):
  // if Settings can't be reached, "Получить ЗН" should be unavailable, not
  // silently assumed on.
  let fivesystemsApiEnabled = false;

  try {
    [departments, workshops, statuses] = await Promise.all([
      getOrgDepartments(),
      getWorkshops(),
      getSlesarkaStatuses(),
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  try {
    fivesystemsApiEnabled = (await getAppSettings()).fivesystems_api_enabled;
  } catch {
    // Already defaults to false above - the rest of the Planner still
    // works fine without this one setting.
  }

  const user = await getCurrentUser();

  return (
    <div className="full-width-page">
      {/* No <h1> here - PlannerShell renders it inline with the
          department/workshop switch (see its own comment) once data is
          loaded; the error path below still needs one of its own. */}
      {error && (
        <div>
          <h1 className="planner-title">Планировщик</h1>
          <div className="card" style={{ borderColor: "var(--down)" }}>
            <p>Не удалось загрузить данные: {error}</p>
          </div>
        </div>
      )}

      {departments && workshops && statuses && (
        <PlannerShell
          departments={departments}
          workshops={workshops}
          statuses={statuses}
          defaultDepartmentId={user?.departmentId ?? null}
          defaultWorkshopId={user?.workshopId ?? null}
          fivesystemsApiEnabled={fivesystemsApiEnabled}
        />
      )}
    </div>
  );
}
