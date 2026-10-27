import { TelephonyTabs } from "@/components/telephony/TelephonyTabs";
import { getLeads, getSourceSummary } from "@/lib/backend-api";
import type { WebsiteLead } from "@/lib/backend-api";

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
};

export default async function TelephonyPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  // Arriving from the conversion donuts on Аналитика: open the "Конверсия"
  // tab for that period, narrowed to the clicked figure's numbers.
  const params = await searchParams;
  let initialSummary;
  let error: string | null = null;
  let leads: WebsiteLead[] | null = null;

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
      <h1>Входящие лиды</h1>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {initialSummary && (
        <TelephonyTabs
          initialSummary={initialSummary}
          initialTab={params.tab === "conversion" ? "conversion" : params.tab === "leads" ? "leads" : "calls"}
          conversionFrom={params.from}
          conversionTo={params.to}
          conversionCohort={params.cohort}
          conversionDepartments={params.departments}
          initialLeads={leads}
          initialLeadId={params.id}
        />
      )}
    </div>
  );
}
