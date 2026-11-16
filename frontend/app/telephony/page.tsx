import { cookies } from "next/headers";

import { TelephonyTabs } from "@/components/telephony/TelephonyTabs";
import {
  getAppSettings,
  getEmployees,
  getLeads,
  getOrgUsers,
  getSlesarkaStatuses,
  getSourceSummary,
  getWorkshops,
} from "@/lib/backend-api";
import type { Employee, SlesarkaStatus, WebsiteLead, Workshop } from "@/lib/backend-api";
import { getCurrentUser } from "@/lib/session";

// Same reasoning as app/settings/page.tsx - never statically prerendered,
// this always needs a fresh backend read.
export const dynamic = "force-dynamic";

type SearchParams = {
  tab?: string;
  from?: string;
  to?: string;
  cohort?: string;
  departments?: string;
  id?: string;
  // From the repair request's "Все звонки" (контроль заявок): the calls of these numbers
  // (comma-separated, 10 digits each) after "since" (Moscow-local "YYYY-MM-DD HH:MM:SS").
  phone?: string;
  since?: string;
  // "Включить заявки на ремонт" of the Аналитика donut the link came from (1 / 0); without it
  // the dashboard's own session cookie decides.
  requests?: string;
  // The planner's "Доска задач" button: the board opens on this цех.
  workshop?: string;
  // "all": the planner's button opens the board on every employee (its counter is per цех).
  employee?: string;
};

// The board opens on "Все" for these roles; everyone else sees their own cards first.
const SEES_EVERYONE_ROLES = ["Админ", "Управляющий"];

export default async function TelephonyPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  // Arriving from the conversion donuts on Аналитика: open the "Конверсия"
  // tab for that period, narrowed to the clicked figure's numbers.
  const params = await searchParams;
  const includeRequests = params.requests
    ? params.requests === "1"
    : (await cookies()).get("conv_requests")?.value === "1";
  let initialSummary;
  let error: string | null = null;
  let leads: WebsiteLead[] | null = null;
  // The board's цех filter; without цеха the board just has no options besides "Все".
  let workshops: Workshop[] = [];
  const user = await getCurrentUser();
  // The board's "Сотрудник" filter, and the employee this login is linked to (the session does
  // not carry it, so it is looked up in the user list).
  let employees: Employee[] = [];
  let currentEmployeeId: string | null = null;

  try {
    workshops = await getWorkshops();
  } catch {
    workshops = [];
  }
  try {
    employees = await getEmployees();
    if (user) currentEmployeeId = (await getOrgUsers()).find((u) => u.id === user.id)?.employee_id ?? null;
  } catch {
    employees = [];
  }
  if (currentEmployeeId && !employees.some((e) => e.id === currentEmployeeId)) currentEmployeeId = null;
  // The planner's record form (drag to «Записан на осмотр»): статусы слесарки and the 5Systems switch.
  let slesarkaStatuses: SlesarkaStatus[] = [];
  let fivesystemsApiEnabled = false;
  try {
    slesarkaStatuses = await getSlesarkaStatuses();
  } catch {
    slesarkaStatuses = [];
  }
  try {
    fivesystemsApiEnabled = (await getAppSettings()).fivesystems_api_enabled;
  } catch {
    fivesystemsApiEnabled = false;
  }
  const boardEmployeeId =
    params.employee === "all" || !user || SEES_EVERYONE_ROLES.includes(user.role) ? null : currentEmployeeId;
  try {
    initialSummary = await getSourceSummary();
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }
  // The site leads are a tab of this page; their failure must not hide the calls.
  try {
    leads = (await getLeads()).leads;
  } catch {
    leads = null;
  }

  return (
    <div className="wide-page">
      <h1>CRM</h1>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {initialSummary && (
        <TelephonyTabs
          initialSummary={initialSummary}
          workshops={workshops}
          boardWorkshopId={params.workshop ?? user?.workshopId ?? null}
          employees={employees}
          currentEmployeeId={currentEmployeeId}
          boardEmployeeId={boardEmployeeId}
          slesarkaStatuses={slesarkaStatuses}
          fivesystemsApiEnabled={fivesystemsApiEnabled}
          initialTab={
            params.tab === "conversion"
              ? "conversion"
              : params.tab === "leads"
                ? "leads"
                : params.tab === "requests"
                  ? "requests"
                  : params.tab === "calls" || params.phone
                    ? "calls"
                    : "board"
          }
          conversionFrom={params.from}
          conversionTo={params.to}
          conversionCohort={params.cohort}
          conversionDepartments={params.departments}
          conversionIncludeRequests={includeRequests}
          initialLeads={leads}
          initialLeadId={params.id}
          historyPhones={params.phone}
          historySince={params.since}
        />
      )}
    </div>
  );
}
