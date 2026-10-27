"use client";

import { useState } from "react";

import { LeadsView } from "@/components/leads/LeadsView";
import { ConversionView } from "@/components/telephony/ConversionView";
import { TelephonyStatsView } from "@/components/telephony/TelephonyStatsView";
import type { SourceSummaryResponse, WebsiteLead } from "@/lib/backend-api";

type TabKey = "calls" | "conversion" | "leads";

const TABS: { key: TabKey; label: string }[] = [
  { key: "calls", label: "Звонки" },
  { key: "conversion", label: "Конверсия звонков" },
  { key: "leads", label: "Заявки с сайта" },
];

/** "Входящие лиды" page tabs: Звонки / Конверсия звонков / Заявки с сайта. The
 * views stay mounted once opened (the inactive one is just hidden) so switching
 * back doesn't throw away a loaded period, an expanded source or a phone-number
 * search. */
export function TelephonyTabs({
  initialSummary,
  initialTab = "calls",
  conversionFrom,
  conversionTo,
  conversionCohort,
  conversionDepartments,
  initialLeads,
  initialLeadId,
}: {
  initialSummary: SourceSummaryResponse;
  initialTab?: TabKey;
  // Deep link from the Аналитика donuts (see ConversionView's props).
  conversionFrom?: string;
  conversionTo?: string;
  conversionCohort?: string;
  conversionDepartments?: string;
  // null = the leads could not be loaded (the tab says so).
  initialLeads: WebsiteLead[] | null;
  // /telephony?tab=leads&id=... (the planner's envelope icon) opens this lead.
  initialLeadId?: string;
}) {
  const [tab, setTab] = useState<TabKey>(initialTab);
  // "Конверсия" loads its (heavier) data only once it's first opened.
  const [conversionOpened, setConversionOpened] = useState(initialTab === "conversion");
  const [leadsOpened, setLeadsOpened] = useState(initialTab === "leads");

  const selectTab = (key: TabKey) => {
    setTab(key);
    if (key === "conversion") setConversionOpened(true);
    if (key === "leads") setLeadsOpened(true);
  };

  return (
    <div>
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

      <div hidden={tab !== "calls"}>
        <TelephonyStatsView initialSummary={initialSummary} />
      </div>
      {conversionOpened && (
        <div hidden={tab !== "conversion"}>
          <ConversionView
            initialStart={conversionFrom}
            initialEnd={conversionTo}
            initialCohort={conversionCohort}
            initialDepartments={conversionDepartments}
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
    </div>
  );
}
