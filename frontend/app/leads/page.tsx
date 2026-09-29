import { LeadsView } from "@/components/leads/LeadsView";
import { getLeads } from "@/lib/backend-api";

// Same reasoning as app/telephony/page.tsx - never statically prerendered,
// this always needs a fresh backend read.
export const dynamic = "force-dynamic";

export default async function LeadsPage() {
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

      {leads && <LeadsView initialLeads={leads} />}
    </div>
  );
}
