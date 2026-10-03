import { BudgetView } from "@/components/budget/BudgetView";
import { getBudgetYear } from "@/lib/backend-api";

// Same reasoning as app/leads/page.tsx - never statically prerendered,
// this always needs a fresh backend read.
export const dynamic = "force-dynamic";

export default async function BudgetPage() {
  const year = new Date().getFullYear();
  let data;
  let error: string | null = null;

  try {
    data = await getBudgetYear(year);
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div className="wide-page">
      <h1>Бюджет</h1>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {data && <BudgetView initialData={data} />}
    </div>
  );
}
