import { TelephonyStatsView } from "@/components/telephony/TelephonyStatsView";
import { getSourceSummary } from "@/lib/backend-api";

// Same reasoning as app/settings/page.tsx - never statically prerendered,
// this always needs a fresh backend read.
export const dynamic = "force-dynamic";

export default async function TelephonyPage() {
  let initialSummary;
  let error: string | null = null;

  try {
    initialSummary = await getSourceSummary();
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div className="wide-page">
      <h1>IP-телефония</h1>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {initialSummary && <TelephonyStatsView initialSummary={initialSummary} />}
    </div>
  );
}
