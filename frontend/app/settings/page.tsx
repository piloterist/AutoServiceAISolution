import { SettingsTabs } from "@/components/settings/SettingsTabs";
import {
  getAppSettings,
  getAuditLog,
  getEmployees,
  getOrgDepartments,
  getOrgUsers,
  getRepairTypes,
  getRoleTabVisibility,
  getSlesarkaStatuses,
  getWorkshops,
} from "@/lib/backend-api";

// Must never be statically prerendered: if the backend happens to be
// reachable at build time, Next.js could otherwise freeze this page with
// build-time data that never updates after deploy until the next rebuild.
export const dynamic = "force-dynamic";

// Reaching this page at all already implies Admin (see middleware.ts) -
// this route doesn't re-check role, same trust boundary as everything else
// server-rendered here.
export default async function SettingsPage() {
  let data;
  let error: string | null = null;

  try {
    const [
      appSettings,
      repairTypesRes,
      departments,
      workshops,
      users,
      statuses,
      employees,
      roleTabVisibility,
      auditLog,
    ] = await Promise.all([
      getAppSettings(),
      getRepairTypes(),
      getOrgDepartments(),
      getWorkshops(),
      getOrgUsers(),
      getSlesarkaStatuses(),
      getEmployees(),
      getRoleTabVisibility(),
      getAuditLog(),
    ]);
    data = {
      appSettings,
      repairTypes: repairTypesRes.repair_types,
      departments,
      workshops,
      users,
      statuses,
      employees,
      roleTabVisibility,
      auditLog,
    };
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div className="wide-page">
      <h1>Настройки</h1>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {data && (
        <SettingsTabs
          appSettings={data.appSettings}
          repairTypes={data.repairTypes}
          departments={data.departments}
          workshops={data.workshops}
          users={data.users}
          statuses={data.statuses}
          employees={data.employees}
          roleTabVisibility={data.roleTabVisibility}
          auditLog={data.auditLog}
        />
      )}
    </div>
  );
}
