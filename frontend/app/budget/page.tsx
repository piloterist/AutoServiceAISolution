import { FinanceView } from "@/components/budget/FinanceView";
import { getBudgetYear, getReceivablesAging } from "@/lib/backend-api";

// Same reasoning as app/leads/page.tsx - never statically prerendered,
// this always needs a fresh backend read.
export const dynamic = "force-dynamic";

export default async function FinancePage() {
  const year = new Date().getFullYear();
  let budget;
  let receivables;
  let error: string | null = null;

  try {
    [budget, receivables] = await Promise.all([getBudgetYear(year), getReceivablesAging()]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div className="wide-page">
      <h1>Финансы</h1>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {budget && receivables && (
        <FinanceView initialBudget={budget} initialReceivables={receivables} />
      )}
    </div>
  );
}
