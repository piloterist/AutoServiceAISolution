import { LeadsView } from "@/components/leads/LeadsView";
import { getLeads } from "@/lib/backend-api";

// Same reasoning as app/telephony/page.tsx - never statically prerendered,
// this always needs a fresh backend read.
export const dynamic = "force-dynamic";

type SearchParams = { id?: string };

export default async function LeadsPage({
  searchParams,
}: {
  // Set by LeadsBadge.tsx's row click (planner's envelope icon) - opens
  // this one lead on arrival, same "?id=" deep-link shape as
  // app/planner/page.tsx's own zn/workshop/date search params.
  searchParams: Promise<SearchParams>;
}) {
  const { id: openLeadId } = await searchParams;
  let leads;
  let error: string | null = null;

  try {
    leads = (await getLeads()).leads;
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div className="wide-page">
      <h1>Заявки</h1>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {leads && <LeadsView initialLeads={leads} initialOpenId={openLeadId} />}
    </div>
  );
}
