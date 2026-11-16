"use client";

import { useState } from "react";

import { TaskBoard } from "@/components/crm/TaskBoard";
import { EmployeesProvider, WorkshopsProvider } from "@/components/crm/WorkshopsContext";
import { LeadsView } from "@/components/leads/LeadsView";
import { WorkOrdersTable } from "@/components/WorkOrdersTable";
import { ConversionView } from "@/components/telephony/ConversionView";
import { TelephonyStatsView } from "@/components/telephony/TelephonyStatsView";
import type { Employee, SourceSummaryResponse, WebsiteLead, Workshop } from "@/lib/backend-api";

type TabKey = "board" | "calls" | "conversion" | "leads" | "requests";

const TABS: { key: TabKey; label: string }[] = [
  { key: "board", label: "Доска задач" },
  { key: "calls", label: "Звонки" },
  { key: "conversion", label: "Конверсия звонков" },
  { key: "leads", label: "Заявки с сайта" },
  { key: "requests", label: "Заявки на ремонт" },
];

/** "CRM" page tabs: Доска задач / Звонки / Конверсия звонков / Заявки с сайта / Заявки на ремонт.
 * The views stay mounted once opened (the inactive one is just hidden) so switching
 * back doesn't throw away a loaded period, an expanded source or a phone-number
 * search. */
export function TelephonyTabs({
  initialSummary,
  workshops,
  boardWorkshopId,
  employees,
  currentEmployeeId,
  boardEmployeeId,
  initialTab = "board",
  conversionFrom,
  conversionTo,
  conversionCohort,
  conversionDepartments,
  conversionIncludeRequests,
  initialLeads,
  initialLeadId,
  historyPhones,
  historySince,
}: {
  initialSummary: SourceSummaryResponse;
  /** The board's цех filter options. */
  workshops: Workshop[];
  /** The цех the board opens on - the user's own or the planner badge's; "Все" if none. */
  boardWorkshopId?: string | null;
  /** The directory's employees: the board's "Сотрудник" filter and the dialog's list. */
  employees: Employee[];
  /** The employee the logged-in user is linked to (preselected in the "На контроль" dialog). */
  currentEmployeeId: string | null;
  /** The board opens on this employee - the user's own, but "Все" (null) for Админ / Управляющий. */
  boardEmployeeId?: string | null;
  initialTab?: TabKey;
  // Deep link from the Аналитика donuts (see ConversionView's props).
  conversionFrom?: string;
  conversionTo?: string;
  conversionCohort?: string;
  conversionDepartments?: string;
  conversionIncludeRequests?: boolean;
  // null = the leads could not be loaded (the tab says so).
  initialLeads: WebsiteLead[] | null;
  // /telephony?tab=leads&id=... (the planner's envelope icon) opens this lead.
  initialLeadId?: string;
  // /telephony?phone=...&since=... (repair request's "Все звонки"): opens the phone-number history.
  historyPhones?: string;
  historySince?: string;
}) {
  const [tab, setTab] = useState<TabKey>(initialTab);
  // "Конверсия" loads its (heavier) data only once it's first opened.
  const [conversionOpened, setConversionOpened] = useState(initialTab === "conversion");
  const [leadsOpened, setLeadsOpened] = useState(initialTab === "leads");
  // The requests table fetches the work orders list (heavy) - only once its tab is first opened.
  const [requestsOpened, setRequestsOpened] = useState(initialTab === "requests");

  const selectTab = (key: TabKey) => {
    setTab(key);
    if (key === "conversion") setConversionOpened(true);
    if (key === "leads") setLeadsOpened(true);
    if (key === "requests") setRequestsOpened(true);
  };

  return (
    <WorkshopsProvider value={workshops}>
      <EmployeesProvider value={{ employees, currentEmployeeId }}>
      <div className="admin-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={t.key === tab ? "admin-tab admin-tab--on" : "admin-tab"}
            onClick={() => selectTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div hidden={tab !== "board"}>
        <TaskBoard
          workshops={workshops}
          initialWorkshopId={boardWorkshopId}
          employees={employees}
          initialEmployeeId={boardEmployeeId}
          active={tab === "board"}
        />
      </div>
      <div hidden={tab !== "calls"}>
        <TelephonyStatsView initialSummary={initialSummary} historyPhones={historyPhones} historySince={historySince} />
      </div>
      {conversionOpened && (
        <div hidden={tab !== "conversion"}>
          <ConversionView
            initialStart={conversionFrom}
            initialEnd={conversionTo}
            initialCohort={conversionCohort}
            initialDepartments={conversionDepartments}
            includeRequests={conversionIncludeRequests}
          />
        </div>
      )}
      {leadsOpened && (
        <div hidden={tab !== "leads"}>
          {initialLeads ? (
            <LeadsView initialLeads={initialLeads} initialOpenId={initialLeadId} />
          ) : (
            <div className="card" style={{ borderColor: "var(--down)" }}>
              <p>Не удалось загрузить заявки с сайта</p>
            </div>
          )}
        </div>
      )}
      {requestsOpened && (
        <div hidden={tab !== "requests"}>
          <WorkOrdersTable requestsMode />
        </div>
      )}
      </EmployeesProvider>
    </WorkshopsProvider>
  );
}
